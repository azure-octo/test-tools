from ghapi.all import GhApi
import requests
import json
import os
import sys
import urllib
import time
import threading
import concurrent

api = GhApi(owner=sys.argv[1], repo=sys.argv[2])


class FileCache():
    def __init__(self, path='/tmp/scrape_tests/.cache/'):
        self.cache_dir = path
        os.makedirs(path, exist_ok=True)
        self.threads = []

    def get(self, key, fetch_url):
        filename = self.cache_dir + '/' + key + ".zip"
        
        try:
            os.stat(filename)
            sys.stderr.write(f"{fetch_url} cached. Skipping download.\n")
            return filename
        except FileNotFoundError:
            pass


        sys.stderr.write(f"{fetch_url} not cached. Downloading.\n")
        headers = {"Authorization": f"token {os.getenv('GITHUB_TOKEN')}"}
        
        backoff = 1.0


        while True:
            response = requests.get(fetch_url, headers=headers)
            if response.status_code == 200:
                with open(filename, "wb") as fh:
                    fh.write(response.content)
               
                return filename
            else:
                sys.stderr.write(f"Got HTTP error (retrying): {response.status_code}\n")
                time.sleep(backoff)
                if backoff < 30:
                    backoff += backoff

        return None

    def prefetch(self, prefetch_artifacts, batch_size=15):
        futures = []
        with concurrent.futures.ThreadPoolExecutor() as executor:
            while True:
                for i in range(batch_size - len(futures)):
                    prefetch_artifact = next(prefetch_artifacts)
                    key = f"{prefetch_artifact.name}.{prefetch_artifact.id}"
                    
                    futures.append( (executor.submit(self.get, key, prefetch_artifact.archive_download_url), prefetch_artifact) )
           
                if len(futures):
                    future, artifact = futures.pop(0)
                    yield future.result(), artifact

class AsyncRequestor(threading.Thread):
    def run(self):
        response = None
        backoff = 1.0
        while response is None:
            try:
                response = api.actions.list_artifacts_for_repo(per_page=100, page=self._args[0])
                self.response = response
            except urllib.error.HTTPError as e:
                sys.stderr.write(f"Http error thread_id {threading.get_ident()} (retrying): {str(e)}\n")
                time.sleep(backoff)
                if backoff < 30:
                    backoff += backoff

    def join(self):
        threading.Thread.join(self)
        return self.response

class TestArtifacts:
    def __init__(self, start_page = 1):
        self.available_artifacts = {}
        self.container_logs = {}

        self.cache = FileCache()
        
        self.next_page = start_page
        self.artifact_generator = self.get_next_artifact()

    def get_available_test_results(self):
        self.get_artifacts(500)
    
    def get_next_artifact(self, test_suites=None):
        responses = []
        threads = []
        while True:
            for i in range(15 - len(threads)):
                thread = AsyncRequestor(args=(self.next_page,))
                self.next_page += 1
                thread.start()
                threads.append(thread)

            if len(responses) == 0:
                responses.append(threads.pop(0).join())
            response = responses.pop(0)
            for artifact in response.artifacts:
                if '.json' in artifact.name or '_test' in artifact.name:
                    if test_suites is None or artifact.name in test_suites:
                        yield artifact


    def get_artifacts(self, batch_size=200):
        retries = 3
        response = None
        while retries > 0:
            try:
                response = api.actions.list_artifacts_for_repo(per_page=100, page=self.next_page)
                break
            except urllib.error.HTTPError as e:
                sys.stderr.write(f"Http error (retrying): {str(e)}\n")
                retries -= 1

        artifact_count = 0
        for artifact in self.artifact_generator:
            if artifact_count > batch_size:
                break
            if '.json' in artifact.name or '_test' in artifact.name:
                if artifact.name not in self.available_artifacts:
                    self.available_artifacts[artifact.name] = []
                if artifact.id in [artifact.id for artifact in self.available_artifacts[artifact.name]]:
                    sys.stderr.write(f'Duplicated artifact id returned from the API: {artifact.id}\n')
                self.available_artifacts[artifact.name].append(artifact)
                artifact_count += 1




