from ghapi.all import GhApi
import requests
import json
import os
import sys

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

        sys.stderr.write(f"{fetch_url} not cached. Downloading.\n")
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
        self.container_logs = {}

        self.cache = FileCache()
        
        self.next_page = start_page

    def get_available_test_results(self, num_pages=5):
        for i in range(num_pages):
            self.get_page()


    def get_page(self):
        response = api.actions.list_artifacts_for_repo(per_page=100, page=self.next_page)
        for artifact in response.artifacts:
            if '.json' in artifact.name or '_test' in artifact.name:
                if artifact.name not in self.available_artifacts:
                    self.available_artifacts[artifact.name] = []
                self.available_artifacts[artifact.name].append(artifact)
        self.next_page += 1


