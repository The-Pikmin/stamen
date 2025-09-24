import pytest
from app import app as flask_app  # Import your Flask app instance


@pytest.fixture
def app():
    """Create and configure a new app instance for each test."""
    yield flask_app


@pytest.fixture
def client(app):
    """A test client for the app."""
    return app.test_client()


def test_home_route(client):
    """
    GIVEN a Flask application
    WHEN the '/' route is requested (GET)
    THEN check that the response is valid
    """
    response = client.get("/")
    assert response.status_code == 200
    assert b"Hello, this is the backend server!" in response.data


def test_get_message_route(client):
    """
    GIVEN a Flask application
    WHEN the '/api/message' route is requested (GET)
    THEN check that the response is a valid JSON message
    """
    response = client.get("/api/message")
    expected_json = {"message": "This is a message from the backend."}

    assert response.status_code == 200
    assert response.content_type == "application/json"
    assert response.get_json() == expected_json
