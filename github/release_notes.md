### What's Improved
- Added a new action `Get Server URL`
- Following changes were made in the action `Push Changes`:
  - Renamed the parameter `Commit Message` to `Commit Summary`
  - Added a new parameter `Commit Description`
- In the action `Create Issue Comment`, the parameter `Comment type` is now richtext.
- Added a new parameter `Repository Type` to select Organization or User as a repository type in the following actions:
  - Merge Branch
  - List Fork Repositories
  - Fork Organization Repository
- Updated output schema of the action `List Pull Request`
- Added new CICD playbooks to support the `Continuous Delivery` solution pack. 
### What's Fixed
- Fixed a connector health check where it should fail for invalid `Username`.


