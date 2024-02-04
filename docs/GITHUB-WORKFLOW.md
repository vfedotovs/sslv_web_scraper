Github workflow checklist
=========================
### 1. Create Milestones and Issues using github.com website or gh cli


### 2. Create new branch for single issue 
```sh
git checkout -b issue-123-fix-bug
```


### 3. Implement fix and comit code change
```sh
git add .
git commit -m "Fix issue #123: Describe the fix"
```

### 4. push branche to github 
```sh
git push origin issue-123-fix-bug
```

### 5. Create pull request using website or gh cli

### 6. Discuss and merge pull request

### 7. Create tag to apropriate branch
```sh
# Ensure you are on the main branch
git checkout main

# Pull the latest changes
git pull origin main

# Tag the commit with a version number
git tag -a v1.0.0 -m "Release v1.0.0"

# Push the tag to the remote repository
git push origin v1.0.0
```

### 8. Create Release:
- After merging, you may decide to create a release. 
  A release typically corresponds to a specific version of your software.

- Go to the GitHub Releases section and create a new release.
  Specify the version number, release title, and include relevant release notes.


### 9. Update Changelog file:
- Keep a Changelog file in your project to document changes for each release. 
  This file helps users and contributors understand what has been added,
  changed, or fixed in each version.
- Update the Changelog file with the new changes.


### 10. Update Documentation:
- Update your project's documentation to reflect any changes introduced in this release.
  This may include updating README files, API documentation, user guides, etc.


### 11. Deploy your application or service with the latest changes.
- Depending on your deployment process, this may involve pushing updates 
  to production servers, updating containers, or deploying to cloud services.


### 12. Run Post-Deployment Testing:
- Perform necessary tests to ensure that the deployed application is 
  working correctly in the production environment.


#### 13. Monitor the deployed application for any issues.
- Monitoring and Rollback (if needed):
- If critical issues are discovered, consider rolling back to the previous version.
