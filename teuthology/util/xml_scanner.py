import os
import logging
import yaml
from collections import defaultdict
from lxml import etree

log = logging.Logger(__name__)


class XMLScanner():
    def __init__(self, client=None, yaml_path=None) -> None:
        self.yaml_data = []
        self.yaml_path = yaml_path
        self.client = client

    def scan_all_files_in_dir(self, dir_path: str, ext: str):
        """
        :param dir_path: Scan all files here. Example: /path/to/dir/
        :param ext     : Extension of files to scan. Example: "xml" or "log"
        """
        (_, stdout, _) = self.client.exec_command(f'ls -d {dir_path}*.{ext}', timeout=200)
        files = stdout.read().decode().split('\n')
        log.info("XML_DEBUG: all file paths are " + " ".join(files))
        
        errors = []
        for fpath in files:
            error_txt = self.scan_file(fpath)
            if error_txt:
                errors += [error_txt]
            
        self.write_logs()
        return errors

    def scan_file(self, path): 
        if not path:
            return None
        (_, stdout, _) = self.client.exec_command(f'cat {path}', timeout=200)
        if stdout:
            xml_tree = etree.parse(stdout)
            error_txt, error_data = self.get_error(xml_tree)
            if error_data:
                error_data["xml_file"] = path
                self.yaml_data += [error_data]
            return error_txt
        log.debug(f'XML output not found at `{str(path)}`!')

    def get_error(self):
        # defined in inherited classes
        pass
    
    def write_logs(self):
        yamlfile = self.yaml_path
        if self.yaml_data:
            try:
                sftp = self.client.open_sftp()
                remote_yaml_file = sftp.open(yamlfile, "w")
                yaml.safe_dump(self.yaml_data, remote_yaml_file, default_flow_style=False)
                remote_yaml_file.close()
            except Exception as exc: 
                log.exception(exc)
                log.info("XML_DEBUG: write logs error: " + repr(exc))
        else:
            log.info("XML_DEBUG: yaml_data is empty!")


class UnitTestScanner(XMLScanner):
    def __init__(self, client=None) -> None:
        super().__init__(client)
        self.yaml_path = "/home/ubuntu/cephtest/archive/unittest_failures.yaml"

    def get_error_msg(self, xml_path):
        try:
            if xml_path[-1] == "/":
                errors = self.scan_all_files_in_dir(xml_path, "xml")
                if errors:
                    return errors[0]
                log.debug("UnitTestScanner: No error found in XML output")
                return None
            else:
                error = self.scan_file(xml_path)
                self.write_logs()
                return error
        except Exception as exc:
            log.exception(exc)
            log.info("XML_DEBUG: get_error_msg: " + repr(exc))

    def get_error(self, xml_tree):
        """
        Returns message of first error found.
        And stores info of all errors in yaml_data. 
        """
        root = xml_tree.getroot()
        if int(root.get("failures", -1)) == 0 and int(root.get("errors", -1)) == 0:
            log.debug("No failures or errors in unit test.")
            return None, None

        failed_testcases = xml_tree.xpath('.//failure/.. | .//error/..')
        if len(failed_testcases) == 0:
            log.debug("No failures/errors tags found in xml file.")
            return None, None

        error_txt, error_data = "", defaultdict(list)
        for testcase in failed_testcases:
            testcase_name = testcase.get("name", "test-name")
            testcase_suitename = testcase.get("classname", "suite-name")
            for child in testcase:
                if child.tag in ['failure', 'error']:
                    fault_kind = child.tag
                    reason = child.get('message', 'No message found in xml output, check logs.')
                    short_reason = reason[:reason.find('begin captured')] # remove traceback
                    error_data[testcase_suitename] += [{
                            "kind": fault_kind, 
                            "testcase": testcase_name,
                            "message": reason,
                        }]
                    if not error_txt:
                        error_txt = f'{fault_kind.upper()}: Test `{testcase_name}` of `{testcase_suitename}`. Reason: {short_reason}.'
        
        return error_txt, { "failed_testsuites": dict(error_data), "num_of_failures": len(failed_testcases) }    


class ValgrindScanner(XMLScanner):
    def __init__(self, client=None) -> None:
        super().__init__(client)
        self.yaml_path = "/home/ubuntu/cephtest/archive/valgrind.yaml"

    def get_error(self, xml_tree):
        pass 