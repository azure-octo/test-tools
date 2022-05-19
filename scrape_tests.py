from ghapi.all import GhApi
import requests
from zipfile import ZipFile
import json
from termcolor import colored
from prettytable import PrettyTable
from dialog import Dialog
from utils import TestArtifacts, FileCache
import os
import sys


api = GhApi(owner=sys.argv[1], repo=sys.argv[2])

def terminal_size():
    import fcntl, termios, struct
    th, tw, hp, wp = struct.unpack('HHHH',
        fcntl.ioctl(0, termios.TIOCGWINSZ,
        struct.pack('HHHH', 0, 0, 0, 0)))
    return tw, th

class SingleTestSuiteView(TestArtifacts):

    def top_menu(self):
        choices = []
        index = 1
        for artifact in sorted(self.available_artifacts.keys()):
            choices.append((artifact, ''))
            index += 1
        d = Dialog(dialog="dialog")
        code, chosen_test_suite = d.menu('Select from available test outputs', choices=choices)

        if code != d.OK:
            sys.exit(1)

        run_choice = ''

        return chosen_test_suite

    def get_for_test_suite(self, suite_name):
        position = 0
        while True:
            if position >= len(self.available_artifacts[suite_name]):
                self.get_artifacts(batch_size=200)
                continue

            yield self.available_artifacts[suite_name][position]
            position += 1

global_cache = FileCache()
all_artifacts = SingleTestSuiteView()

object_process_counts = {}

class TestSuite:
    def __init__(self, test_suite_name):
        self.run_results = {}
        self.name = test_suite_name
        self.prefetch_artifacts = all_artifacts.get_for_test_suite(self.name)
        self.run_ids = set()
    
    def generate_results_table(self, num_columns=1):
        if len(self.run_ids) > num_columns:
            return
        for filepath, artifact in global_cache.prefetch(self.prefetch_artifacts):
            try:
                with ZipFile(filepath) as zfile:
                    for index in range(len(zfile.namelist())):
                        try:
                            for line in zfile.read(zfile.namelist()[index]).decode('utf-8').split('\n'):
                                if len(line) and ".json" in zfile.namelist()[index]:
                                    event = json.loads(line)

                                    key = event["Package"]

                                    self.run_ids.add(artifact.id)

                                    if 'Test' in event:
                                        key += ":" + event['Test']

                                    if key not in self.run_results:
                                        self.run_results[key] = {artifact.id: {'output': ''}}
                                    if artifact.id not in self.run_results[key]:
                                        self.run_results[key][artifact.id] = {'output': ''}

                                    if event['Action'] in ('pass', 'fail'):
                                        self.run_results[key][artifact.id]['result'] = event['Action']

                                    if event['Action'] == 'output':
                                        self.run_results[key][artifact.id]['output'] += event['Output']
                        except Exception as e:
                            sys.stdout.write(f"Error reading artifact: {artifact} {str(e)} {zfile.namelist()[index]}\n")

            except Exception as e:
                sys.stdout.write(f"Error reading artifact: {artifact} {str(e)}\n")
            
            if len(self.run_ids) > num_columns:
                return

    def drilldown(self, run):
        choices = []
        run_choice = sorted(self.run_ids, reverse=True)[run-1]
        for run in all_artifacts.get_for_test_suite(self.name):
            if run.id == run_choice:
                test_results = { key: self.run_results[key][run_choice]['result'] for key in self.run_results.keys() if run_choice in self.run_results[key] and 'result' in self.run_results[key][run_choice] }
                choices = []
                for test in sorted(self.run_results.keys()):
                    result = 'no_data'

                    try:
                        result = self.run_results[test][run_choice]['result']
                    except KeyError:
                        pass
                    color = ''
                    if result == 'pass':
                        color ='\\Zb\\Z2'
                    if result == 'fail':
                        color = '\\Zb\\Z1'
                    choices.append((str(test), color + result))
        
                d = Dialog(dialog="dialog")

                code, test_choice = d.menu('Select from available test outputs', width=190, height=100, choices=choices, colors=True)
        
                if code != d.OK:
                    return False

                print(self.run_results[test_choice][run_choice]['output'])
                return True

    def generate_table_string(self, start = 0, length = 1):
        output = PrettyTable()

        run_headers = ['Tests']
        run_failures = 0
        i = start + 1
        for run in sorted(self.run_ids, reverse=True)[start:length]:
            if 'fail' in [self.run_results[test][run]['result'] for test in self.run_results if run in self.run_results[test] and 'result' in self.run_results[test][run]]:
                run_headers.append(colored(str(i), 'red'))
                run_failures += 1
            else:
                run_headers.append(colored(str(i), 'green'))
            i += 1


        output.field_names = run_headers + ["Failure Rate"]

        for test in sorted(self.run_results.keys()):
            row = [test]

            failures = 0
            successes = 0
            for run in sorted(self.run_ids, reverse=True)[start:length]:
                try:
                    if self.run_results[test][run]['result'] == 'pass':
                        row.append(colored('  ', 'grey', 'on_green'))
                        successes += 1
                    
                    if self.run_results[test][run]['result'] == 'fail':
                        row.append(colored('  ', 'grey', 'on_red'))
                        failures += 1

                except KeyError:
                    row.append(colored('  ', 'grey', 'on_white'))
            if successes + failures == 0:
                row.append(f"N/A")
            else:
                row.append(f"{failures / (successes + failures):.2f}")
            output.add_row(row)

        output.add_row(run_headers + [f'{run_failures / length:.2f}'])

        output.align = "l"

        return output.get_string()


    def print_test_history(self):
        cw, ch = terminal_size()
        if len(self.run_results) == 0:
            self.generate_results_table()
        # First generate the table to see how wide it is
        table = self.generate_table_string(0, 1)
        table_width = len(table.split("\n")[0])
        

        # If we've got more space, keep fetching results until we can fill the screen
        if cw > table_width:
            remaining_runs = int((cw - table_width)/5)
            sys.stderr.write(f"Console width: {cw}, table size: {table_width}. Should have room for  {remaining_runs} more test runs\n")
            target_artifacts = remaining_runs + 1
            while len(self.run_ids) < target_artifacts:
                self.generate_results_table(target_artifacts)
            table = self.generate_table_string(0,target_artifacts)
            table_width = len(table.split("\n")[0])


        table = self.generate_table_string(0,table_width)

        print(table)

from getkey import getkey

all_artifacts.get_available_test_results()
chosen_test_suite = all_artifacts.top_menu()
all_test_suites = {chosen_test_suite: TestSuite(chosen_test_suite)}

all_test_suites[chosen_test_suite].print_test_history()
print('Press "d" to drilldown. "q" to quit. "m" for top menu')
while True:
    choice = getkey()

    if choice == "q":
        sys.exit(0)

    if choice == "o":
        all_test_suites[chosen_test_suite].print_test_history()
        print('Press "d" to drilldown. "q" to quit. "m" for top menu')

    if choice == "d":
        try:
            run = int(input("Select run id: "))
        except ValueError:
            print('Invalid run id\nPress "d" to drilldown. "q" to quit. "o" for overview')
            continue
        if not all_test_suites[chosen_test_suite].drilldown(run):
            all_test_suites[chosen_test_suite].print_test_history()
            print('Press "d" to drilldown. "q" to quit. "m" for top menu')
        else:
            print('Press "q" to quit. "o" for overview. "m" for top menu')

    if choice == "m":
        chosen_test_suite = all_artifacts.top_menu()

        if chosen_test_suite not in all_test_suites:
            all_test_suites[chosen_test_suite] = TestSuite(chosen_test_suite)

        #ts.generate_results_table()
        all_test_suites[chosen_test_suite].print_test_history()
        print('Press "d" to drilldown. "q" to quit. "m" for top menu')

