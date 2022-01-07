from ghapi.all import GhApi
import requests
from zipfile import ZipFile
import json
from termcolor import colored
from prettytable import PrettyTable
from dialog import Dialog
from utils import FileCache, TestArtifacts
import os
import sys
import re
import urllib
import threading
import time

api = GhApi(owner=sys.argv[1], repo=sys.argv[2])

class AsyncRequestor(threading.Thread):
    def run(self):
        response = None
        backoff = 1.0
        while response is None:
            try:
                response = api.actions.list_artifacts_for_repo(per_page=100, page=self._args[0])
                print("Reading page ", self._args[0])
                self.response = response
            except urllib.error.HTTPError as e:
                sys.stderr.write(f"Http error thread_id {threading.get_ident()} (retrying): {str(e)}\n")
                time.sleep(backoff)
                if backoff < 30:
                    backoff += backoff

    def join(self):
        threading.Thread.join(self)
        return self.response

class MultiSelectArtifactGenerator(TestArtifacts):
    def top_menu(self):
        choices = []
        index = 1
        for artifact in sorted(self.available_artifacts.keys()):
            choices.append((artifact, '', False))
            index += 1
        d = Dialog(dialog="dialog")
        code, chosen_test_suite = d.checklist('Select from available test outputs', choices=choices)

        if code != d.OK:
            sys.exit(1)

        run_choice = ''

        return chosen_test_suite

    def get_for_test_suite(self, suite_names):
        for suite_name in suite_names:
            for artifact in self.available_artifacts[suite_name]:
                yield artifact

        for artifact in self.get_next_artifact(suite_names):
            yield artifact
        


global_cache = FileCache()
all_artifacts = MultiSelectArtifactGenerator()

output_filename = None
if len(sys.argv)>=5:
    output_filename = sys.argv[4]

class TestSuite:
    def __init__(self, test_suite_names):
        self.run_results = {}
        self.names = test_suite_names
    
    def grep_results(self, regex_string):
        #try:
        with open(output_filename, "w") as fh:
            self.print_outputs(regex_string, [sys.stdout, fh])
        #except:
        #    self.print_outputs(regex_string, [sys.stdout])

    def print_outputs(self, regex_string, outputs):
        prefetch_artifacts = all_artifacts.get_for_test_suite(self.names)
        artifacts = all_artifacts.get_for_test_suite(self.names)
        for artifact in artifacts:
            global_cache.prefetch(prefetch_artifacts)
            with ZipFile(global_cache.get(f"{artifact.name}.{artifact.id}", artifact.archive_download_url)) as zfile:
                for index in range(len(zfile.namelist())):
                    try:
                        for line in zfile.read(zfile.namelist()[index]).decode('utf-8').split('\n'):
                            if len(line) and ".json" in zfile.namelist()[index]:
                                event = json.loads(line)

                                if event['Action'] == 'output':
                                    regex = re.compile(regex_string)
                                    match_obj = regex.match(event['Output'])
                                    if match_obj is not None:
                                        for output in outputs:
                                            output.write(f"{artifact.name} {line}\n")

                    except Exception as e:
                        print("Error reading artifact:", artifact, str(e), zfile.namelist()[index], line)




all_artifacts.get_available_test_results()
chosen_test_suites = all_artifacts.top_menu()

ts = TestSuite(chosen_test_suites)

ts.grep_results(sys.argv[3])
