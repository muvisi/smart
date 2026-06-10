from rest_framework import serializers
from .models import DebitCredit


class DebitCreditSerializer(serializers.ModelSerializer):
    class Meta:
        model = DebitCredit
        fields = "__all__"