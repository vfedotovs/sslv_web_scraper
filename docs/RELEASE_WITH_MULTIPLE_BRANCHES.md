-- How to release with multiple branches --

1. Create PR with consistent naming convention:
* PR: merge GH305-issue branch in to dev-1.5.4 branch

2. Merge feat or bug in to for example dev-1.5.4 

3. Use github GUI create release-1.5.6 branch from source dev-1.5.4 branch 

4. Switch to main:
# Ensure you are on the main branch
git switch main

# Pull the latest changes
git pull origin main

5.  Switch to release-1.5.6
git switch release-1.5.6

6. Perform tagging and push tags
git tag -a v1.5.6 -m "Release v1.5.6"
git push origin v1.5.6 


7. Create release using github GUI use correct tag ---

--- Template  for release notes ---

This is a patch release with feature and bug fixes.

What's Changed

Feature enhancements:
[FEATURE] Implement pulling release version from environment file
[FEATURE] Implement SSL for web service in AWS EC2

Bug Fixes:
BUG [#278] (CRITICAL) web_scraper scrapes only first page and is not scraping other 2 pages
BUG [#267] DB container keep logging FATAL: database "new_docker_user" does not exist


8. Once release notes created create new PR to merge release in to main (production)

8.1 Create consistent PR naming:
PR: merge release-1.5.6 branch in to main branch

9. Perform merge release-1.5.6 in to main

10. To create new dev cycle

11. Create new branch dev-1.5.7 from release-1.5.6 (for next release-1.5.7)

12. If hotfix needed best create hotfix branch - and merge it hotfix > dev > release > main

