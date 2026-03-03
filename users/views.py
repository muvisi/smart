from rest_framework import viewsets
from .models import Users
from .serializers import UsersSerializer
from rest_framework import viewsets
from .models import Users
from .serializers import UsersSerializer
from rest_framework.permissions import IsAdminUser  # Only admin can create users

from rest_framework import viewsets, status
from rest_framework.response import Response
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from .models import Users
from .serializers import UsersSerializer
import random
import string

class UsersViewSet(viewsets.ModelViewSet):
    queryset = Users.objects.all()
    serializer_class = UsersSerializer

    def create(self, request, *args, **kwargs):
        # Generate a random password if not provided
        data = request.data.copy()
        if not data.get('password'):
            data['password'] = ''.join(random.choices(string.ascii_letters + string.digits, k=10))

        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        # Send the welcome email
        if user.email:
            send_welcome_email(user.username, user.email, data['password'], user.first_name, user.last_name)

        return Response(serializer.data, status=status.HTTP_201_CREATED)


# ---------------- Email Function ----------------
def send_welcome_email(username, email, password, first_name="", last_name=""):
    subject = "Welcome to Madison Healthcare!"
    from_email = "haisnotifications@madison.co.ke"
    
    # HTML template
    html_content = render_to_string("emails/welcome.html", {
        "first_name": first_name,
        "last_name": last_name,
        "username": username,
        "password": password,
    })

    msg = EmailMultiAlternatives(subject, "", from_email, [email,"mwangangimuvisi@gmail.com"])
    msg.attach_alternative(html_content, "text/html")
    msg.send()
    
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from .serializers import LoginSerializer

class LoginAPIView(APIView):
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']

        # Generate JWT token
        refresh = RefreshToken.for_user(user)
        return Response({
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'uuid': str(user.uuid),
            'username': user.username
        }, status=status.HTTP_200_OK)