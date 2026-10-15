from django.urls import path

from .views import heatmap_view, routes_view

urlpatterns = [
    path("routes/", routes_view, name="routes"),
    path("heatmap/", heatmap_view, name="heatmap"),
]
