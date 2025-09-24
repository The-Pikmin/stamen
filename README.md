<div align="center">
<img width="125" height="125" src="https://emojicdn.elk.sh/🌱?style=apple"/>
<h1>Stamen - Plant Disease Diagnosis Backend</h1>
</div>

[!NOTE]
This is the backend application for the senior design project, "A07 - Computer Vision System for Plant Disease Diagnosis".

# Introduction

Welcome to the backend for the Plant Disease Diagnosis application! This is a Flask application that serves a REST API to the frontend. It handles image uploads, processes them with a machine learning model, and returns a diagnosis.

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

# Running Tests

To run the unit tests for this project, use the command:

`pytest`

# Contributing

We welcome contributions from the team! If you would like to contribute to this repository, please read our [Contributing Guide](./CONTRIBUTING.md) for our full workflow and standards.

## 📝 License

This repository is licensed under the [MIT License](./LICENSE).
