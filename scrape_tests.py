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


api = GhApi(owner=sys.argv[1], repo=sys.argv[2])

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


run_results = {}

runs = set()

available_artifacts = {}

for page in range(6):
    response = api.actions.list_artifacts_for_repo(per_page=100, page=page)
    for artifact in response.artifacts:
        if '.json' in artifact.name:
            if artifact.name not in available_artifacts:
                available_artifacts[artifact.name] = []
            available_artifacts[artifact.name].append(artifact)

choices = []
index = 1
for artifact in sorted(available_artifacts.keys()):
    choices.append((artifact, ''))
    index += 1
d = Dialog(dialog="dialog")
code, chosen_artifact = d.menu('Select from available test outputs', choices=choices)

if code != d.OK:
    sys.exit(1)

print(chosen_artifact)

cache = FileCache()

run_choice = ''
if len(sys.argv) > 3 and sys.argv[3] == '--drilldown':
    choices = []

    run_ids = set([artifact.id for artifact in available_artifacts[chosen_artifact]]) 

    for run in sorted(run_ids, reverse=True):
        choices.append((str(run), ''))
    print(choices)
    code, run_choice = d.menu('Select from available test outputs', choices=choices)
    if code != d.OK:
        sys.exit(1)
    test_results = {} 
    for artifact in available_artifacts[chosen_artifact]:
        if artifact.id == int(run_choice):
            with ZipFile(cache.get(f"{chosen_artifact}.{run_choice}", artifact.archive_download_url)) as zfile:
                for line in zfile.read(zfile.namelist()[0]).decode('utf-8').split('\n'):
                    if len(line):
                        event = json.loads(line)

                        key = event["Package"]

                        if 'Test' in event:
                            key += ":" + event['Test']

                        runs.add(artifact.id)
                        if key not in test_results:
                            test_results[key] = []

                        test_results[key].append(event)

                choices = []
                for test in sorted(test_results.keys()):
                    result = 'pass'
                    if 'fail' in [event['Action'] for event in test_results[test] if 'Action' in event]:
                        result = 'fail'
                    choices.append((str(test), result))
                
                code, test_choice = d.menu('Select from available test outputs', width=190, height=100, choices=choices)

                for event in test_results[test_choice]:
                    if event['Action'] == 'output':
                        print(event['Output'])
            break


    sys.exit(0)


for artifact in available_artifacts[chosen_artifact]:
    if artifact.name == chosen_artifact:

        with ZipFile(cache.get(f"{artifact.name}.{artifact.id}", artifact.archive_download_url)) as zfile:
            for line in zfile.read(zfile.namelist()[0]).decode('utf-8').split('\n'):
                if len(line):
                    event = json.loads(line)

                    key = event["Package"]

                    if 'Test' in event:
                        key += ":" + event['Test']

                    runs.add(artifact.id)
                    if key not in run_results:
                        run_results[key] = {}

                    if event['Action'] in ('pass', 'fail'):
                        run_results[key][artifact.id] = event['Action']

output = PrettyTable()

run_headers = ['Tests']
i = 1
for run in sorted(runs):
    if 'fail' in [run_results[test][run] for test in run_results if run in run_results[test]]:
        run_headers.append(colored(str(i), 'red'))
    else:
        run_headers.append(colored(str(i), 'green'))
    i+=1


output.field_names = run_headers + ["Failure Rate"]

for test in sorted(run_results.keys()):
    row = [test]

    failures = 0
    successes = 0
    for run in sorted(runs):
        try:
            if run_results[test][run] == 'pass':
                row.append(colored('  ', 'grey', 'on_green'))
                successes += 1
            
            if run_results[test][run] == 'fail':
                row.append(colored('  ', 'grey', 'on_red'))
                failures += 1

        except KeyError:
            row.append(colored('  ', 'grey', 'on_white'))
    if successes + failures == 0:
        row.append(f"N/A")
    else:
        row.append(f"{failures / (successes + failures):.2f}")
    output.add_row(row)

output.align = "l"
print(output)


