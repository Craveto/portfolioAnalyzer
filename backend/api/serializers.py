from django.contrib.auth.models import User
from rest_framework import serializers

from accounts.models import UserProfile
from portfolio.models import Holding, Portfolio, Sector, Stock, Transaction
from watchlist.models import PriceAlert, WatchlistItem


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)

    class Meta:
        model = User
        fields = ("id", "username", "email", "password")

    def create(self, validated_data):
        user = User(username=validated_data["username"], email=validated_data.get("email", ""))
        user.set_password(validated_data["password"])
        user.save()
        return user


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "username", "email")


class UserProfileSerializer(serializers.ModelSerializer):
    default_portfolio_id = serializers.PrimaryKeyRelatedField(
        source="default_portfolio",
        queryset=Portfolio.objects.all(),
        required=False,
        allow_null=True,
        write_only=True,
    )
    default_portfolio = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = UserProfile
        fields = ("full_name", "bio", "default_redirect", "default_portfolio", "default_portfolio_id", "updated_at")

    def get_default_portfolio(self, obj):
        if not obj.default_portfolio_id:
            return None
        return {"id": obj.default_portfolio_id, "name": obj.default_portfolio.name}


class AccountSerializer(serializers.Serializer):
    user = UserSerializer()
    profile = UserProfileSerializer()


class ProfileUpdateSerializer(serializers.Serializer):
    username = serializers.CharField(required=False, max_length=150)
    email = serializers.EmailField(required=False, allow_blank=True)
    full_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    bio = serializers.CharField(required=False, allow_blank=True, max_length=280)
    default_redirect = serializers.ChoiceField(required=False, choices=["dashboard", "account"])
    default_portfolio_id = serializers.IntegerField(required=False, allow_null=True)


class PasswordChangeSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=6)


class SectorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sector
        fields = ("id", "name")


class StockSerializer(serializers.ModelSerializer):
    sector = SectorSerializer(read_only=True)

    class Meta:
        model = Stock
        fields = ("id", "symbol", "name", "exchange", "sector")


class PortfolioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Portfolio
        fields = ("id", "name", "market", "created_at")


class HoldingSerializer(serializers.ModelSerializer):
    stock = StockSerializer(read_only=True)
    stock_id = serializers.PrimaryKeyRelatedField(source="stock", queryset=Stock.objects.all(), write_only=True)

    class Meta:
        model = Holding
        fields = ("id", "stock", "stock_id", "qty", "avg_buy_price", "updated_at")


class TransactionSerializer(serializers.ModelSerializer):
    stock = StockSerializer(read_only=True)
    stock_id = serializers.PrimaryKeyRelatedField(source="stock", queryset=Stock.objects.all(), write_only=True)

    class Meta:
        model = Transaction
        fields = ("id", "stock", "stock_id", "side", "qty", "price", "realized_pnl", "executed_at")

    def validate(self, attrs):
        side = attrs.get("side")
        qty = attrs.get("qty")
        price = attrs.get("price")
        if side not in ("BUY", "SELL"):
            raise serializers.ValidationError({"side": "Must be BUY or SELL"})
        if qty is None or qty <= 0:
            raise serializers.ValidationError({"qty": "Must be > 0"})
        if price is None or price <= 0:
            raise serializers.ValidationError({"price": "Must be > 0"})
        return attrs


class WatchlistItemSerializer(serializers.ModelSerializer):
    stock = StockSerializer(read_only=True)
    last_price = serializers.FloatField(read_only=True)

    class Meta:
        model = WatchlistItem
        fields = ("id", "stock", "created_at", "last_price")


class WatchlistAddSerializer(serializers.Serializer):
    stock_symbol = serializers.CharField(max_length=32)
    stock_name = serializers.CharField(required=False, allow_blank=True, max_length=200)


class PriceAlertSerializer(serializers.ModelSerializer):
    stock = StockSerializer(read_only=True)
    last_price = serializers.FloatField(read_only=True)

    class Meta:
        model = PriceAlert
        fields = ("id", "stock", "direction", "target_price", "is_active", "triggered_at", "created_at", "last_price")


class PriceAlertCreateSerializer(serializers.Serializer):
    stock_symbol = serializers.CharField(max_length=32)
    stock_name = serializers.CharField(required=False, allow_blank=True, max_length=200)
    direction = serializers.ChoiceField(choices=["ABOVE", "BELOW"])
    target_price = serializers.DecimalField(max_digits=18, decimal_places=4)


class TradeCreateSerializer(serializers.Serializer):
    stock_id = serializers.PrimaryKeyRelatedField(queryset=Stock.objects.all(), required=False)
    stock_symbol = serializers.CharField(required=False, max_length=32)
    stock_name = serializers.CharField(required=False, max_length=200, allow_blank=True)
    side = serializers.ChoiceField(choices=["BUY", "SELL"])
    qty = serializers.DecimalField(max_digits=18, decimal_places=4)
    price = serializers.DecimalField(max_digits=18, decimal_places=4)

    def validate(self, attrs):
        if not attrs.get("stock_id") and not attrs.get("stock_symbol"):
            raise serializers.ValidationError({"stock_symbol": "Provide stock_symbol (or stock_id)."})
        if attrs.get("qty") is not None and attrs["qty"] <= 0:
            raise serializers.ValidationError({"qty": "Must be > 0"})
        if attrs.get("price") is not None and attrs["price"] <= 0:
            raise serializers.ValidationError({"price": "Must be > 0"})
        return attrs
