from ghapi.all import GhApi
import requests
from zipfile import ZipFile
from io import BytesIO
import json
from termcolor import colored
from prettytable import PrettyTable
from dialog import Dialog
import os
import sys

from azure.storage.blob import BlobServiceClient, BlobClient, ContainerClient, __version__


api = GhApi(owner=sys.argv[1], repo=sys.argv[2])

def terminal_size():
    import fcntl, termios, struct
    th, tw, hp, wp = struct.unpack('HHHH',
        fcntl.ioctl(0, termios.TIOCGWINSZ,
        struct.pack('HHHH', 0, 0, 0, 0)))
    return tw, th

class FileCache:
    def __init__(self, path='/tmp/scrape_tests/.cache/'):
        self.cache_dir = path
        os.makedirs(path, exist_ok=True)

    def get(self, key, fetch_url):
        filename = self.cache_dir + '/' + key + ".zip"

        print("Would download", fetch_url)

        try:
            os.stat(filename)
            return filename
        except FileNotFoundError:
            pass


        headers = {"Authorization": f"token {os.getenv('GITHUB_TOKEN')}"}
        response = requests.get(fetch_url, headers=headers)

        if response.status_code == 200:
            with open(filename, "wb") as fh:
                fh.write(response.content)
           
            return filename

        return None

class TestArtifacts:

    def __init__(self, start_page = 0):


        self.available_artifacts = {}

        self.cache = FileCache()
        
        self.next_page = start_page

    def get_available_test_results(self, num_pages=5):
        for i in range(num_pages):
            self.get_page()


    def get_page(self):
        response = api.actions.list_artifacts_for_repo(per_page=100, page=self.next_page)
        for artifact in response.artifacts:
            if '.json' in artifact.name:
                if artifact.name not in self.available_artifacts:
                    self.available_artifacts[artifact.name] = []
                self.available_artifacts[artifact.name].append(artifact)
        self.next_page += 1


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
        return self.available_artifacts[suite_name]

global_cache = FileCache()
all_artifacts = TestArtifacts()

class TestSuite:
    def __init__(self, test_suite_name):
        self.run_results = {}
        self.name = test_suite_name
    
    def generate_results_table(self):
        self.run_ids = set()
        for artifact in all_artifacts.get_for_test_suite(self.name):
            try:
                with ZipFile(global_cache.get(f"{artifact.name}.{artifact.id}", artifact.archive_download_url)) as zfile:
                    for index in range(len(zfile.namelist())):
                        for line in zfile.read(zfile.namelist()[index]).decode('utf-8').split('\n'):
                            if len(line):
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
                print("Error reading artifact:", artifact, str(e))


    def drilldown(self, run):
        choices = []
        run_choice = sorted(self.run_ids)[run-1]
        for run in all_artifacts.get_for_test_suite(self.name):
            if run.id == run_choice:
                test_results = { key: self.run_results[key][run_choice]['result'] for key in self.run_results.keys() if run_choice in self.run_results[key] and 'result' in self.run_results[key][run_choice] }
                print(test_results)
                choices = []
                for test in sorted(test_results.keys()):
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

                print(self.run_results[test_choice][run_choice]['output'])
                break

    def generate_table_string(self, start = 0, length = 1):
        output = PrettyTable()

        run_headers = ['Tests']
        run_failures = 0
        i = start + 1
        for run in sorted(self.run_ids)[start:length]:
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
            for run in sorted(self.run_ids)[start:length]:
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

        # First generate the table to see how wide it is
        table = self.generate_table_string(0, 1)
        table_width = len(table.split("\n")[0])

        # If we've got more space, keep fetching results until we can fill the screen
        if cw > table_width:
            print(f"Console width: {cw}, table size: {table_width}. Should have room for  {(cw - table_width)/5} more runs")
            target_artifacts = int((cw - table_width)/5) + 1
            while len(all_artifacts.get_for_test_suite(self.name)) < target_artifacts:
                all_artifacts.get_page()
            self.generate_results_table()
            table = self.generate_table_string(0,target_artifacts)
            table_width = len(table.split("\n")[0])


        table = self.generate_table_string(0,target_artifacts)

        print(table)





'''
if len(sys.argv) > 3 and sys.argv[3] == '--csv-out-dir':

    run_ids = set([artifact.id for artifact in available_artifacts[chosen_artifact]]) 

    for run in sorted(run_ids, reverse=True):
        filename = sys.argv[4] + '/' + str(run) + '.csv'
        with open(filename, 'w') as fh:
            test_results = {}
            fh.write('test,run_id,test_suite,run_timestamp,result,output\n')
            for artifact in available_artifacts[chosen_artifact]:
                if artifact.id == int(run):
                    print(artifact)
                    try:
                        with ZipFile(cache.get(f"{chosen_artifact}.{run}", artifact.archive_download_url)) as zfile:
                            for index in range(len(zfile.namelist())):
                                for line in zfile.read(zfile.namelist()[index]).decode('utf-8').split('\n'):
                                    if len(line):
                                        event = json.loads(line)

                                        key = event["Package"]

                                        if 'Test' in event:
                                            key += ":" + event['Test']

                                        runs.add(artifact.id)
                                        if key not in test_results:
                                            test_results[key] = []

                                        test_results[key].append(event)

                            for test in sorted(test_results.keys()):
                                result = 'no_data'
                                if 'fail' in [event['Action'] for event in test_results[test] if 'Action' in event]:
                                    result = 'fail'
                                if 'pass' in [event['Action'] for event in test_results[test] if 'Action' in event]:
                                    result = 'pass'
                                
                                output_string = ""
                                for event in test_results[test]:
                                    if event['Action'] == 'output':
                                        output_string += event['Output'].replace('\n', '\\n').replace(',', ';')

                                fh.write(f"{test},{run},{chosen_artifact},{artifact.created_at},{result},{output_string}\n")
                        

                            break
                    except:
                        print("Error reading artifact: %s", artifact)

        connect_str = os.getenv('AZURE_STORAGE_CONNECTION_STRING')
        container_name = 'test-output'
        blob_service_client = BlobServiceClient.from_connection_string(connect_str)

        # Create a blob client using the local file name as the name for the blob
        blob_client = blob_service_client.get_blob_client(container=container_name, blob=filename)
        try:
            blob_client.delete_blob(delete_snapshots="include")
        except:
            pass

        print("\nUploading to Azure Storage as blob:\n\t" + filename)

        # Upload the created file
        with open(filename, "rb") as data:
                blob_client.upload_blob(data)
    sys.exit(0)
'''


from getkey import getkey

all_artifacts.get_available_test_results()
chosen_test_suite = all_artifacts.top_menu()

ts = TestSuite(chosen_test_suite)

ts.generate_results_table()
ts.print_test_history()
print('Press "d" to drilldown. "q" to quit. "m" for top menu')
while True:
    choice = getkey()

    if choice == "q":
        sys.exit(0)

    if choice == "o":
        ts.print_test_history()
        print('Press "d" to drilldown. "q" to quit. "m" for top menu')

    if choice == "d":
        try:
            run = int(input("Select run id: "))
        except ValueError:
            print('Invalid run id\nPress "d" to drilldown. "q" to quit. "o" for overview')
            continue
        ts.drilldown(run)
        print('Press "d" to drilldown. "q" to quit. "o" for overview. "m" for top menu')

    if choice == "m":
        chosen_test_suite = all_artifacts.top_menu()

        ts = TestSuite(chosen_test_suite)

        ts.generate_results_table()
        ts.print_test_history()
        print('Press "d" to drilldown. "q" to quit. "m" for top menu')

