### What's Improved
- Added a new action `Get Server URL` 
- Added select parameter `Repository Type` to specify the Organization and User type repository in following actions:
  - Merge Branch
  - List Fork Repositories
  - Fork Organization Repository
- Updated type `Comment` parameter text to richtext in `Create Issue Comment` action.
- Renamed `Commit Message` parameter to `Commit Summary` and added `Commit Description` parameter in `Push Changes` action.
- Updated output schema of `List Pull Request` action.
### What's Fixed
- Fixed a connector health check where it should fail for invalid `Username`.
