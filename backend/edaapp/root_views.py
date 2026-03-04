from django.http import HttpResponse, JsonResponse


def index(request):
    return JsonResponse(
        {
            "name": "EDA Portfolio Analyzer API",
            "status": "ok",
            "paths": {
                "admin": "/admin/",
                "market_summary": "/api/market/summary/",
                "auth_register": "/api/auth/register/",
                "auth_login": "/api/auth/login/",
                "me": "/api/auth/me/",
                "stocks": "/api/stocks/",
            },
        }
    )


def favicon(request):
    # Avoid noisy 404s in the browser devtools.
    return HttpResponse(status=204)
