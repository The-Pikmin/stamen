# Contributing to the Plant Diagnosis Backend

Welcome, and thank you for considering contributing to the Plant Diagnosis Backend! Your help is greatly appreciated. Before you begin, please read through this document to understand our development process and guidelines.

# Setup

1. Install [Python](https://www.python.org/downloads/) (v3.10 or higher).

2. Clone this repository to your local machine.

3. Navigate to the root directory of the repository.

4. Create and activate a virtual environment:

```
# Create the virtual environment
python -m venv venv

# Activate it (macOS/Linux)
source venv/bin/activate

# Activate it (Windows)
.\venv\Scripts\activate
```

5. Install all project dependencies with `pip install -r requirements-dev.txt`.

## Environment Variables

Create a `.env` file in the root of the repository by copying the example file:

```
cp .env.example .env
```

This file will be used for any secret keys or configuration variables needed for the application.

# Development

To start the local Flask development server, run the following command. This will typically launch the application on `http://127.0.0.1:5000`.

```
flask run
```

# Testing Your Changes

In your pull request, it's important to provide a detailed test plan.

For all backend changes, please outline the steps you took to test your changes. This could include new or updated unit tests, or manual testing with tools like Postman or cURL.

Ensure all new endpoints and logic are covered by unit tests. You can run the full test suite with pytest.

# Git Workflow

Our project uses two main branches:

- `main`: Contains only stable, production-ready code. Direct pushes are disabled.

- `beta`: The primary development and integration branch. All feature branches are merged here.

1. **Create a Feature Branch**: Always create your new branch from the `beta` branch. Use a descriptive name (e.g., `feat/diagnose-endpoint` or `fix/image-processing-bug`).

2. **Make Commits**: For commit messages, please keep them concise, descriptive, and in all lowercase. We recommend reading [How to Write a Git Commit Message for guidance](https://chris.beams.io/posts/git-commit/).

3. **Open a Pull Request**: When your feature is complete, push your branch to GitHub and open a pull request to merge it into the `beta` branch. Provide a clear description of your changes and include your testing plan.

**Promoting to Production** (`main`)
Changes are promoted from `beta` to `main` only when `beta` is stable and ready for a release. This is done by a maintainer of the project.

A "Release" pull request is opened from `beta` into `main`.

After a final review, the pull request is merged.

A new version tag (e.g., `v1.1.0`) is created on the `main` branch to mark the release.

# Before Submitting a Pull Request

Please ensure your code keeps our CI checks green! Run these commands locally to verify everything is correct before you push.

Your code is formatted correctly: `black .`

Your code passes linting: `flake8 .`

All unit tests pass: `pytest`

Most importantly, make sure your code and especially your API endpoints are well-documented and easy for others to understand!
