# Github-org-repo-status

## GitHub Single Repository Activity Tracker

This script gathers activity data for all contributors to a specific GitHub repository in an organization.

### Requirements

- Python 3.7+
- Install dependencies:
  ```bash
  pip install aiohttp
  ```

### Usage

You can run the script using environment variables or command line arguments.

#### 1. Using Environment Variables

Set your GitHub credentials and repository info:

```bash
export GITHUB_TOKEN=your_github_token
export GITHUB_ORG=your_org_name
export GITHUB_REPO=your_repo_name
python script.py
```

#### 2. Using Command Line Arguments

```bash
python script.py --token YOUR_TOKEN --org YOUR_ORG --repo YOUR_REPO --days 30
```

Optional arguments:

- `--days`: Number of days to look back (default: 30)
- `--output`: Output directory for reports
- `--concurrent`: Max concurrent requests (default: 20)

### Output

Reports are saved in a folder named `github_activities_<repo_name>/` by default. Each contributor will have a summary report in a separate `.txt` file.

### Example

```bash
export GITHUB_TOKEN=ghp_xxx
export GITHUB_ORG=DiamondvivaLtd
export GITHUB_REPO=bellavire-backend
python script.py
```

or

```bash
python script.py --token ghp_xxx --org DiamondvivaLtd --repo bellavire-backend --days 30
```
