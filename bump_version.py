#!/usr/bin/env python3
"""
Version bump utility for Artwork Uploader for Plex.

This script helps automate version updates and creates git tags for releases.

Usage:
    python bump_version.py patch   # 0.5.1 -> 0.5.2
    python bump_version.py minor   # 0.5.1 -> 0.6.0
    python bump_version.py major   # 0.5.1 -> 1.0.0
    python bump_version.py 0.6.0   # Set specific version
"""

import re
import sys
import subprocess
from pathlib import Path


def get_current_version():
    """Read current version from __version__.py"""
    version_file = Path(__file__).parent / "core" / "__version__.py"
    content = version_file.read_text()
    match = re.search(r'__version__ = ["\']([^"\']+)["\']', content)
    if match:
        return match.group(1)
    raise ValueError("Could not find version in __version__.py")


def parse_version(version_str):
    """Parse version string into components"""
    match = re.match(r'^(\d+)\.(\d+)\.(\d+)(?:-(.+))?$', version_str)
    if not match:
        raise ValueError(f"Invalid version format: {version_str}")

    major, minor, patch, pre = match.groups()
    return int(major), int(minor), int(patch), pre or "patch"


def bump_version(current, bump_type):
    """Calculate new version based on bump type"""
    major, minor, patch, pre = parse_version(current)

    if bump_type == "major":
        return f"{major + 1}.0.0"
    elif bump_type == "minor":
        return f"{major}.{minor + 1}.0"
    elif bump_type == "patch":
        return f"{major}.{minor}.{patch + 1}"
    else:
        # Assume it's a specific version string
        try:
            parse_version(bump_type)  # Validate format
            return bump_type
        except ValueError:
            raise ValueError(f"Invalid bump type or version: {bump_type}")


def update_version_file(new_version):
    """Update __version__.py with new version"""
    version_file = Path(__file__).parent / "core" / "__version__.py"
    content = version_file.read_text()

    # Parse new version
    major, minor, patch, pre = parse_version(new_version)

    # Update version string
    content = re.sub(
        r'__version__ = ["\'][^"\']+["\']',
        f'__version__ = "{new_version}"',
        content
    )

    # Update version info tuple
    content = re.sub(
        r'__version_info__ = \([^)]+\)',
        f'__version_info__ = ({major}, {minor}, {patch}, "{pre}")',
        content
    )

    version_file.write_text(content)
    print(f"✓ Updated {version_file}")


def git_commit_and_tag(version):
    """Commit version change and create git tag"""
    try:
        # Check if git repo is clean (except for __version__.py)
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True
        )

        # Filter out __version__.py from changes
        other_changes = [
            line for line in result.stdout.strip().split('\n')
            if line and '__version__.py' not in line
        ]

        if other_changes and other_changes != ['']:
            print("⚠ Warning: You have uncommitted changes:")
            for line in other_changes:
                print(f"  {line}")
            response = input("Continue anyway? (y/N): ")
            if response.lower() != 'y':
                print("Aborted.")
                return False

        # Stage version file
        subprocess.run(
            ["git", "add", "core/__version__.py"],
            check=True
        )

        # Commit
        subprocess.run(
            ["git", "commit", "-m", f"Bump version to {version}"],
            check=True
        )
        print(f"✓ Committed version bump")

        # Create tag
        tag = f"v{version}"
        subprocess.run(
            ["git", "tag", "-a", tag, "-m", f"Release {tag}"],
            check=True
        )
        print(f"✓ Created tag {tag}")

        print(f"\n📦 Ready to release!")
        print(f"\nNext steps:")
        print(f"  1. Review the changes: git show {tag}")
        print(f"  2. Push the commit: git push")
        print(f"  3. Push the tag: git push origin {tag}")
        print(f"\nThe GitHub Action will automatically create a release when the tag is pushed.")

        return True

    except subprocess.CalledProcessError as e:
        print(f"✗ Git error: {e}")
        return False


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)

    bump_type = sys.argv[1]

    try:
        current = get_current_version()
        print(f"Current version: {current}")

        new_version = bump_version(current, bump_type)
        print(f"New version: {new_version}")

        # Confirm
        response = input(f"\nUpdate version from {current} to {new_version}? (y/N): ")
        if response.lower() != 'y':
            print("Aborted.")
            sys.exit(0)

        # Update files
        update_version_file(new_version)

        # Git operations
        response = input(f"\nCommit and tag this version? (y/N): ")
        if response.lower() == 'y':
            if git_commit_and_tag(new_version):
                print(f"\n✓ Version {new_version} is ready for release!")
            else:
                print("\n✗ Failed to create git commit/tag")
                sys.exit(1)
        else:
            print("\nVersion file updated but not committed.")
            print("You can manually commit with: git add core/__version__.py && git commit -m 'Bump version'")

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
