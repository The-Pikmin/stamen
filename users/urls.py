from django.urls import path
from .views import (
    home,
    get_message,
    predict,
    get_current_user,
    update_profile,
    upload_image,
    save_scan,
    scan_history,
)

urlpatterns = [
    path("", home, name="home"),
    path("message/", get_message, name="get_message"),
    path("predict/", predict, name="predict"),
    path("me/", get_current_user, name="current-user"),
    path("me/profile/", update_profile, name="update-profile"),
    path("images/upload/", upload_image, name="upload_image"),
    path("scans/", save_scan, name="save-scan"),
    path("scans/list/", scan_history, name="scan-history"),
]
