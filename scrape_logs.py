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
import re

from azure.storage.blob import BlobServiceClient, BlobClient, ContainerClient, __version__


api = GhApi(owner=sys.argv[1], repo=sys.argv[2])

class FileCache:
    def __init__(self, path='/tmp/scrape_tests/.cache/'):
        self.cache_dir = path
        os.makedirs(path, exist_ok=True)

    def get(self, key, fetch_url):
        filename = self.cache_dir + '/' + key + ".zip"

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

for page in range(5):
    response = api.actions.list_artifacts_for_repo(per_page=100, page=page)
    for artifact in response.artifacts:
        if 'container_logs' in artifact.name:
            if artifact.name not in available_artifacts:
                available_artifacts[artifact.name] = []
            available_artifacts[artifact.name].append(artifact)

print(available_artifacts)
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
for artifact in available_artifacts[chosen_artifact]:
    if artifact.name == chosen_artifact:

        with ZipFile(cache.get(f"{artifact.name}.{artifact.id}", artifact.archive_download_url)) as zfile:
            init_times = []
            for zipfile in zfile.namelist():
                if 'daprd' in zipfile:
                    for line in zfile.read(zipfile).decode('utf-8').split('\n'):
                        if "Init Elapsed" in line:
                            print(line)
                            match_obj = re.match(".*Init Elapsed (\d+\.\d+).*", line)
                            if match_obj is not None:
                                init_times.append(float(match_obj.group(1)))
            if len(init_times) >0:
                print(artifact)
                print(f"Average Init Elapsed: {sum(init_times)/len(init_times)}")

