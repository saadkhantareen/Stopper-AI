from django.urls import path

from .views import health_view, heatmap_view, routes_view

urlpatterns = [
    path("routes/", routes_view, name="routes"),
    path("heatmap/", heatmap_view, name="heatmap"),
    path("health/", health_view, name="health"),
]
