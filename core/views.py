from django.shortcuts import render


def home(request):
    return render(request, "core/index.html")

def login_view(request):
    return render(request, "core/login.html")