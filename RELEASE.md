# Release Process

This document describes the automated release process for Artwork Uploader for Plex.

## Overview

The release process is fully automated using GitHub Actions. When you push a version tag, it will automatically:
- Verify the version matches `core/__version__.py`
- Generate a changelog from git commits
- Create source code archives
- Build executables (if PyInstaller spec exists)
- Create a GitHub release with all artifacts
- Update the `latest` tag

## Quick Release

### Option 1: Using the bump_version.py script (Recommended)

```bash
# Bump patch version (0.5.1 -> 0.5.2)
python3 bump_version.py patch

# Bump minor version (0.5.1 -> 0.6.0)
python3 bump_version.py minor

# Bump major version (0.5.1 -> 1.0.0)
python3 bump_version.py major

# Set specific version
python3 bump_version.py 0.6.0
```

The script will:
1. Update `core/__version__.py`
2. Create a git commit
3. Create a git tag (e.g., `v0.5.2`)
4. Prompt you to push

Then just push:
```bash
git push
git push origin v0.5.2  # Push the tag to trigger release
```

### Option 2: Manual Process

1. **Update version in `core/__version__.py`**:
   ```python
   __version__ = "0.5.2"
   __version_info__ = (0, 5, 2, "patch")
   ```

2. **Commit the version change**:
   ```bash
   git add core/__version__.py
   git commit -m "Bump version to 0.5.2"
   ```

3. **Create and push tag**:
   ```bash
   git tag -a v0.5.2 -m "Release v0.5.2"
   git push
   git push origin v0.5.2
   ```

## What Happens Next

Once you push the tag, GitHub Actions will:

1. **Verify** - Check that the tag version matches `__version__.py`
2. **Build** - Create source archives and executables
3. **Release** - Create a GitHub release with:
   - Auto-generated changelog from commits
   - Source code (zip and tar.gz)
   - Executable builds (if available)
4. **Tag** - Update the `latest` tag to point to this release

## Pre-releases

For alpha, beta, or release candidate versions:

```bash
python3 bump_version.py 0.6.0-beta
git push
git push origin v0.6.0-beta
```

Versions containing `alpha`, `beta`, or `rc` will automatically be marked as pre-releases on GitHub.

## Writing Good Commit Messages

Since the changelog is auto-generated from commits, write clear, descriptive commit messages:

**Good:**
- `Fix KeyError when deleting scheduled tasks`
- `Add support for MediUX season posters`
- `Improve error handling in scheduler service`

**Avoid:**
- `fix bug`
- `updates`
- `WIP`

## Checking Releases

After pushing a tag, you can:
- View the GitHub Action progress: https://github.com/mscodemonkey/artwork-uploader-plex/actions
- See the release when complete: https://github.com/mscodemonkey/artwork-uploader-plex/releases

## Troubleshooting

### Version mismatch error
If the workflow fails with a version mismatch:
1. Check that `core/__version__.py` matches your tag
2. Update the version file and amend your commit
3. Delete and recreate the tag:
   ```bash
   git tag -d v0.5.2
   git push origin :refs/tags/v0.5.2
   git tag -a v0.5.2 -m "Release v0.5.2"
   git push origin v0.5.2
   ```

### Build failures
If the build fails:
- Check the GitHub Actions logs for details
- You can manually edit the release on GitHub
- The workflow is in `.github/workflows/release.yml`

## Semantic Versioning

We follow [Semantic Versioning](https://semver.org/):

- **MAJOR** version (1.0.0): Incompatible API changes
- **MINOR** version (0.6.0): New functionality (backwards compatible)
- **PATCH** version (0.5.2): Bug fixes (backwards compatible)

## Notes

- The `latest` tag always points to the most recent release
- Users can check for updates by comparing their version to the latest tag
- Releases are public and visible to all users
- Draft releases are not supported with this automation (releases go live immediately)
