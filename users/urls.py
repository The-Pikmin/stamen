from django.urls import path
from .views import (
    home,
    get_message,
    predict,
    get_current_user,
    update_profile,
    upload_image,
    image_list,
    image_detail,
    save_scan,
    scan_history,
    scan_detail,
    disease_list,
    disease_detail,
)

urlpatterns = [
    path("", home, name="home"),
    path("message/", get_message, name="get_message"),
    path("predict/", predict, name="predict"),
    path("me/", get_current_user, name="current-user"),
    path("me/profile/", update_profile, name="update-profile"),
    path("images/upload/", upload_image, name="upload_image"),
    path("images/list/", image_list, name="image-list"),
    path("images/<int:pk>/", image_detail, name="image-detail"),
    path("scans/", save_scan, name="save-scan"),
    path("scans/list/", scan_history, name="scan-history"),
    path("scans/<int:pk>/", scan_detail, name="scan-detail"),
    path("diseases/", disease_list, name="disease-list"),
    path(
        "diseases/<str:genus>/<str:disease_name>/",
        disease_detail,
        name="disease-detail",
    ),
]
