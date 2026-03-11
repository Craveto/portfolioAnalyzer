from django.db import models


class CachedPayload(models.Model):
    key = models.CharField(max_length=120, unique=True)
    payload = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.key
