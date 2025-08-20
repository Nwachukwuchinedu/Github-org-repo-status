#!/usr/bin/env python3
"""
GitHub Single Repository Activity Tracker
High-performance script to gather comprehensive activity data for all organization members in a specific repository
"""

import asyncio
import aiohttp
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import argparse
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor
import time

@dataclass
class ActivityData:
    username: str
    repo_name: str
    activity_type: str
    date: str
    details: Dict[str, Any]

class GitHubRepoTracker:
    def __init__(self, token: str, org_name: str, repo_name: str, max_concurrent: int = 20):
        self.token = token
        self.org_name = org_name
        self.repo_name = repo_name
        self.full_repo_name = f"{org_name}/{repo_name}"
        self.base_url = "https://api.github.com"
        self.headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        self.max_concurrent = max_concurrent
        self.session = None
        self.semaphore = None
        
    async def __aenter__(self):
        connector = aiohttp.TCPConnector(limit=100, limit_per_host=30)
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        self.session = aiohttp.ClientSession(
            headers=self.headers,
            connector=connector,
            timeout=timeout
        )
        self.semaphore = asyncio.Semaphore(self.max_concurrent)
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def make_request(self, url: str, params: Optional[Dict] = None) -> Optional[List[Dict]]:
        """Make rate-limited API request with error handling"""
        async with self.semaphore:
            try:
                async with self.session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data if isinstance(data, list) else [data]
                    elif response.status == 403:
                        # Rate limit hit
                        reset_time = int(response.headers.get('X-RateLimit-Reset', 0))
                        wait_time = max(0, reset_time - int(time.time())) + 1
                        print(f"Rate limit hit, waiting {wait_time} seconds...")
                        await asyncio.sleep(wait_time)
                        return await self.make_request(url, params)
                    else:
                        print(f"API request failed: {response.status} for {url}")
                        return None
            except Exception as e:
                print(f"Request error for {url}: {str(e)}")
                return None

    async def check_repo_exists(self) -> bool:
        """Check if the repository exists and is accessible"""
        print(f"🔍 Checking if repository {self.full_repo_name} exists...")
        url = f"{self.base_url}/repos/{self.full_repo_name}"
        
        data = await self.make_request(url)
        if data and len(data) > 0:
            repo_info = data[0]
            print(f"✅ Repository found: {repo_info.get('full_name')}")
            print(f"   Description: {repo_info.get('description', 'No description')}")
            print(f"   Language: {repo_info.get('language', 'Not specified')}")
            print(f"   Stars: {repo_info.get('stargazers_count', 0)}")
            return True
        else:
            print(f"❌ Repository {self.full_repo_name} not found or not accessible")
            return False

    async def get_repo_contributors(self) -> List[str]:
        """Get all contributors to the repository"""
        print(f"👥 Fetching contributors for {self.full_repo_name}...")
        contributors = []
        page = 1
        
        while True:
            url = f"{self.base_url}/repos/{self.full_repo_name}/contributors"
            params = {"page": page, "per_page": 100}
            
            data = await self.make_request(url, params)
            if not data:
                break
                
            batch_contributors = [contributor["login"] for contributor in data if contributor["type"] == "User"]
            contributors.extend(batch_contributors)
            
            if len(data) < 100:
                break
            page += 1
            
        print(f"✅ Found {len(contributors)} contributors")
        return contributors

    async def get_org_members(self) -> List[str]:
        """Get all organization members"""
        print(f"🔍 Fetching organization members for {self.org_name}...")
        members = []
        page = 1
        
        while True:
            url = f"{self.base_url}/orgs/{self.org_name}/members"
            params = {"page": page, "per_page": 100}
            
            data = await self.make_request(url, params)
            if not data:
                break
                
            batch_members = [member["login"] for member in data]
            members.extend(batch_members)
            
            if len(batch_members) < 100:
                break
            page += 1
            
        print(f"✅ Found {len(members)} organization members")
        return members

    async def get_commits_for_member(self, member: str, since: str) -> List[ActivityData]:
        """Get commits for a specific member in the repository"""
        url = f"{self.base_url}/repos/{self.full_repo_name}/commits"
        params = {
            "author": member,
            "since": since,
            "per_page": 100
        }
        
        commits_data = await self.make_request(url, params)
        if not commits_data:
            return []
            
        activities = []
        for commit in commits_data:
            # Get detailed commit info
            commit_url = f"{self.base_url}/repos/{self.full_repo_name}/commits/{commit['sha']}"
            detailed_commit = await self.make_request(commit_url)
            
            if detailed_commit and detailed_commit[0]:
                commit_detail = detailed_commit[0]
                stats = commit_detail.get('stats', {})
                files = commit_detail.get('files', [])
                
                file_changes = []
                for file in files:
                    file_changes.append({
                        'filename': file.get('filename', ''),
                        'additions': file.get('additions', 0),
                        'deletions': file.get('deletions', 0),
                        'changes': file.get('changes', 0),
                        'status': file.get('status', '')
                    })
                
                activity = ActivityData(
                    username=member,
                    repo_name=self.full_repo_name,
                    activity_type="commit",
                    date=commit['commit']['author']['date'],
                    details={
                        'sha': commit['sha'],
                        'message': commit['commit']['message'],
                        'total_additions': stats.get('additions', 0),
                        'total_deletions': stats.get('deletions', 0),
                        'total_changes': stats.get('total', 0),
                        'files_changed': file_changes,
                        'url': commit['html_url']
                    }
                )
                activities.append(activity)
                
        return activities

    async def get_pull_requests_for_member(self, member: str) -> List[ActivityData]:
        """Get pull requests for a specific member in the repository"""
        activities = []
        
        # Get PRs created by member
        for state in ['open', 'closed']:
            url = f"{self.base_url}/repos/{self.full_repo_name}/pulls"
            params = {
                "creator": member,
                "state": state,
                "per_page": 100,
                "sort": "updated",
                "direction": "desc"
            }
            
            prs_data = await self.make_request(url, params)
            if not prs_data:
                continue
                
            for pr in prs_data:
                # Get PR files and changes
                files_url = f"{self.base_url}/repos/{self.full_repo_name}/pulls/{pr['number']}/files"
                files_data = await self.make_request(files_url)
                
                file_changes = []
                total_additions = 0
                total_deletions = 0
                
                if files_data:
                    for file in files_data:
                        additions = file.get('additions', 0)
                        deletions = file.get('deletions', 0)
                        file_changes.append({
                            'filename': file.get('filename', ''),
                            'additions': additions,
                            'deletions': deletions,
                            'changes': file.get('changes', 0),
                            'status': file.get('status', '')
                        })
                        total_additions += additions
                        total_deletions += deletions
                
                activity = ActivityData(
                    username=member,
                    repo_name=self.full_repo_name,
                    activity_type="pull_request",
                    date=pr['created_at'],
                    details={
                        'number': pr['number'],
                        'title': pr['title'],
                        'state': pr['state'],
                        'merged': pr.get('merged', False),
                        'total_additions': total_additions,
                        'total_deletions': total_deletions,
                        'files_changed': file_changes,
                        'url': pr['html_url'],
                        'created_at': pr['created_at'],
                        'updated_at': pr['updated_at'],
                        'merged_at': pr.get('merged_at')
                    }
                )
                activities.append(activity)
                
        return activities

    async def get_issues_for_member(self, member: str) -> List[ActivityData]:
        """Get issues for a specific member in the repository"""
        activities = []
        
        for state in ['open', 'closed']:
            url = f"{self.base_url}/repos/{self.full_repo_name}/issues"
            params = {
                "creator": member,
                "state": state,
                "per_page": 100,
                "sort": "updated",
                "direction": "desc"
            }
            
            issues_data = await self.make_request(url, params)
            if not issues_data:
                continue
                
            for issue in issues_data:
                # Skip pull requests (they appear in issues API)
                if issue.get('pull_request'):
                    continue
                    
                activity = ActivityData(
                    username=member,
                    repo_name=self.full_repo_name,
                    activity_type="issue",
                    date=issue['created_at'],
                    details={
                        'number': issue['number'],
                        'title': issue['title'],
                        'state': issue['state'],
                        'labels': [label['name'] for label in issue.get('labels', [])],
                        'url': issue['html_url'],
                        'created_at': issue['created_at'],
                        'updated_at': issue['updated_at'],
                        'closed_at': issue.get('closed_at')
                    }
                )
                activities.append(activity)
                
        return activities

    async def get_member_activity(self, member: str, since_date: str) -> List[ActivityData]:
        """Get all activity for a specific member in the repository"""
        print(f"📊 Processing activity for {member} in {self.full_repo_name}...")
        
        tasks = [
            self.get_commits_for_member(member, since_date),
            self.get_pull_requests_for_member(member),
            self.get_issues_for_member(member)
        ]
        
        # Execute all tasks concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        all_activities = []
        for result in results:
            if isinstance(result, list):
                all_activities.extend(result)
            elif isinstance(result, Exception):
                print(f"Error processing {member}: {str(result)}")
                
        return all_activities

    async def track_repository(self, days_back: int = 30) -> Dict[str, List[ActivityData]]:
        """Track only contributors to the repo"""
        since_date = (datetime.now() - timedelta(days=days_back)).isoformat()
        print(f"🚀 Starting GitHub repository tracking for {self.full_repo_name}")
        print(f"📅 Looking back {days_back} days (since {since_date[:10]})")
        # Check if repo exists
        if not await self.check_repo_exists():
            return {}
        # Get contributors only
        print("🎯 Tracking only repository contributors")
        members = await self.get_repo_contributors()
        if not members:
            print("❌ No contributors found or API access denied")
            return {}
        print(f"⚡ Processing {len(members)} contributors for repository {self.full_repo_name}...")
        member_tasks = [self.get_member_activity(member, since_date) for member in members]
        results = await asyncio.gather(*member_tasks, return_exceptions=True)
        member_activities = {}
        for i, result in enumerate(results):
            member = members[i]
            if isinstance(result, list):
                # Only save if the member has at least one commit, PR, or issue in this repo
                if any(a.activity_type in ["commit", "pull_request", "issue"] for a in result):
                    member_activities[member] = result
            else:
                print(f"❌ Failed to process {member}: {str(result)}")
        return member_activities

    def save_to_files(self, activities: Dict[str, List[ActivityData]], output_dir: str = None):
        """Save summary activities to individual files for each contributor"""
        if output_dir is None:
            output_dir = f"github_activities_{self.repo_name}"
        os.makedirs(output_dir, exist_ok=True)
        print(f"💾 Saving activity data to {output_dir}/")
        for member, member_activities in activities.items():
            filename = os.path.join(output_dir, f"{member}.txt")
            with open(filename, 'w', encoding='utf-8') as f:
                # Only summary info
                sorted_activities = sorted(member_activities, key=lambda x: x.date)
                first_date = sorted_activities[0].date if sorted_activities else "N/A"
                last_commit_date = next((a.date for a in reversed(sorted_activities) if a.activity_type == "commit"), "N/A")
                total_commits = sum(1 for a in member_activities if a.activity_type == "commit")
                total_prs = sum(1 for a in member_activities if a.activity_type == "pull_request")
                total_issues = sum(1 for a in member_activities if a.activity_type == "issue")
                total_activities = len(member_activities)
                total_additions = sum(a.details.get('total_additions', 0) for a in member_activities if a.activity_type in ["commit", "pull_request"])
                total_deletions = sum(a.details.get('total_deletions', 0) for a in member_activities if a.activity_type in ["commit", "pull_request"])
                f.write(f"GitHub Activity Report for: {member}\n")
                f.write(f"Repository: {self.full_repo_name}\n")
                f.write(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 80 + "\n\n")
                f.write(f"Date Started Working: {first_date}\n")
                f.write(f"Last Commit Date: {last_commit_date}\n")
                f.write(f"Total Commits: {total_commits}\n")
                f.write(f"Total Pull Requests: {total_prs}\n")
                f.write(f"Total Issues: {total_issues}\n")
                f.write(f"Total Activities: {total_activities}\n")
                f.write(f"Total Changes: +{total_additions} -{total_deletions}\n")
        print(f"✅ Activity reports saved for {len(activities)} contributors")

async def main():
    parser = argparse.ArgumentParser(description="GitHub Single Repository Activity Tracker")
    parser.add_argument("--token", required=True, help="GitHub personal access token")
    parser.add_argument("--org", required=True, help="GitHub organization name")
    parser.add_argument("--repo", required=True, help="Repository name (without org prefix)")
    parser.add_argument("--days", type=int, default=30, help="Days to look back (default: 30)")
    parser.add_argument("--output", help="Output directory (default: github_activities_{repo_name})")
    parser.add_argument("--concurrent", type=int, default=20, help="Max concurrent requests")
    parser.add_argument("--all-contributors", action="store_true", 
                       help="Track all contributors, not just organization members")
    
    args = parser.parse_args()
    
    start_time = time.time()
    
    async with GitHubRepoTracker(args.token, args.org, args.repo, args.concurrent) as tracker:
        activities = await tracker.track_repository(args.days)
        tracker.save_to_files(activities, args.output)
    
    end_time = time.time()
    print(f"🎉 Completed in {end_time - start_time:.2f} seconds")

if __name__ == "__main__":
    # For running without command line args (set your values here)
    TOKEN = os.getenv("GITHUB_TOKEN", "your_github_token_here")
    ORG_NAME = os.getenv("GITHUB_ORG", "your_org_name_here")
    REPO_NAME = os.getenv("GITHUB_REPO", "your_repo_name_here")
    DAYS_BACK = 30
    
    if TOKEN == "your_github_token_here" or ORG_NAME == "your_org_name_here" or REPO_NAME == "your_repo_name_here":
        print("Please set GITHUB_TOKEN, GITHUB_ORG, and GITHUB_REPO environment variables or use command line arguments")
        print("\nUsage examples:")
        print("python script.py --token YOUR_TOKEN --org YOUR_ORG --repo YOUR_REPO --days 30")
        print("python script.py --token YOUR_TOKEN --org YOUR_ORG --repo YOUR_REPO --all-contributors")
        print("\nOr set environment variables:")
        print("export GITHUB_TOKEN=your_token")
        print("export GITHUB_ORG=your_org")
        print("export GITHUB_REPO=your_repo")
        print("python script.py")
    else:
        async def run_with_env():
            async with GitHubRepoTracker(TOKEN, ORG_NAME, REPO_NAME) as tracker:
                activities = await tracker.track_repository(DAYS_BACK)
                tracker.save_to_files(activities)
        asyncio.run(run_with_env())