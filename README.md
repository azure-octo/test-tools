# Dapr Test Dashboard

## Install

Install the dialog package
```bash
brew install dialog
```

Install Python libraries
```bash
pip3 install -r requirements.txt
```

Set your GitHub token environment variable
```bash
export GITHUB_TOKEN=<YOUR-TOKEN-HERE>
```

## Running the test dashboard

```
python3 scrape_tests.py dapr dapr
```

## Test output grep

You can scrape the output of one or more test suites for a particular regex.
```
python3 grep_test_output.py dapr cli ".*expected.*Running.*" output.txt
```

## Failure counts

To get the test failure counts by test for the last N days

```
python3 failure_counts.py dapr dapr 4 
```

## TODO: Document log scraper
