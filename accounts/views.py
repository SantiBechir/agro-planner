from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.shortcuts import redirect, render


def login_view(request):
    if request.user.is_authenticated:
        return redirect("home")

    if request.method == "POST":
        correo = (request.POST.get("email") or "").strip().lower()
        clave = request.POST.get("password")

        try:
            validate_email(correo)
        except ValidationError:
            user = None
        else:
            user = authenticate(request, email=correo, password=clave)
        if user is not None:
            login(request, user)
            return redirect("home")
        else:
            messages.error(request, "Usuario o contraseña incorrectos.")

    return render(request, "core/login.html")


def logout_view(request):
    logout(request)
    return redirect("login")

