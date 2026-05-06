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

from django.contrib.auth import get_user_model
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

User = get_user_model()


class PatchUserAPIView(APIView):

    def patch(self, request, uuid):
        data = request.data

        try:
            user = User.objects.get(uuid=uuid)
        except User.DoesNotExist:
            return Response(
                {"message": "User not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        username = data.get("username")
        email = data.get("email")

        # =========================
        # 🔐 DUPLICATE CHECKS
        # =========================
        if username and User.objects.filter(username=username).exclude(uuid=user.uuid).exists():
            return Response(
                {"message": "Username already taken"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if email and User.objects.filter(email=email).exclude(uuid=user.uuid).exists():
            return Response(
                {"message": "Email already in use"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # =========================
        # ✏️ PARTIAL UPDATE
        # =========================
        if username is not None:
            user.username = username

        if email is not None:
            user.email = email

        if data.get("first_name") is not None:
            user.first_name = data.get("first_name")

        if data.get("last_name") is not None:
            user.last_name = data.get("last_name")

        if data.get("department") is not None:
            user.department = data.get("department")

        user.save()

        return Response({
            "message": "User updated successfully",
            "user": {
                "uuid": str(user.uuid),
                "username": user.username,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "department": getattr(user, "department", None),
            }
        }, status=status.HTTP_200_OK)

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

        if user.email:
            send_welcome_email(user.username, user.email, data['password'], user.first_name, user.last_name)

        return Response(serializer.data, status=status.HTTP_201_CREATED)


#---------------- Email Function ----------------
def send_welcome_email(username, email, password, first_name="", last_name=""):
    subject = "Welcome to Madison Healthcare!"
    from_email = "haisnotifications@madison.co.ke"
    
    # HTML template
    html_content = render_to_string("emails/welcome.html", {
        "first_name": first_name,
        "last_name": last_name,
        "username": username,
        "password": "AD PASSWORD",
    })

    msg = EmailMultiAlternatives(subject, "", from_email, [email,"mwangangimuvisi@gmail.com"])
    msg.attach_alternative(html_content, "text/html")
    msg.send()
    
# from rest_framework.views import APIView
# from rest_framework.response import Response
# from rest_framework import status
# from rest_framework_simplejwt.tokens import RefreshToken
# from .serializers import LoginSerializer

# class LoginAPIView(APIView):
#     def post(self, request):
#         serializer = LoginSerializer(data=request.data)
#         serializer.is_valid(raise_exception=True)
#         user = serializer.validated_data['user']

#         # Generate JWT token
#         refresh = RefreshToken.for_user(user)
#         return Response({
#             'refresh': str(refresh),
#             'access': str(refresh.access_token),
#             'uuid': str(user.uuid),
#             'username': user.username
#         }, status=status.HTTP_200_OK)



from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from .serializers import LoginSerializer
import ldap
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model


User = get_user_model()

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import authenticate
# from django.contrib.auth.models import User
from rest_framework_simplejwt.tokens import RefreshToken
import ldap

from django.contrib.auth import authenticate, get_user_model
from django.db.models import Q
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
import ldap

User = get_user_model()


class LoginAPIView(APIView):

    def post(self, request):
        identifier = request.data.get("username")  # can be username OR email
        password = request.data.get("password")
        login_method = request.data.get("loginMethod", "local")

        if not identifier or not password:
            return Response({
                "message": "Username/email and password are required"
            }, status=status.HTTP_400_BAD_REQUEST)

        # =========================
        # 🔐 LDAP LOGIN FLOW
        # =========================
        if login_method.lower() == "ldap":
            try:
                ldap_server = "ldap://192.168.0.4"

                conn = ldap.initialize(ldap_server)
                conn.protocol_version = 3
                conn.set_option(ldap.OPT_REFERRALS, 0)

                # support email OR username input
                login_id = identifier.split("@")[0] if "@" in identifier else identifier
                user_dn = f"{login_id}@madison.co.ke"

                # authenticate LDAP
                conn.simple_bind_s(user_dn, password)

                # create or get Django user
                user, created = User.objects.get_or_create(
                    username=login_id,
                    defaults={
                        "email": f"{login_id}@madison.co.ke"
                    }
                )

                refresh = RefreshToken.for_user(user)

                return Response({
                    "message": "LDAP Login Successful",
                    "refresh": str(refresh),
                    "access": str(refresh.access_token),
                    "uuid": str(user.uuid),
                    "username": user.username,
                    "department": getattr(user, "department", None),
                    "email": user.email,
                    "auth_source": "ldap"
                }, status=status.HTTP_200_OK)

            except ldap.INVALID_CREDENTIALS:
                return Response({
                    "message": "Invalid LDAP credentials"
                }, status=status.HTTP_401_UNAUTHORIZED)

            except ldap.SERVER_DOWN:
                return Response({
                    "message": "LDAP server unavailable"
                }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

            except Exception as e:
                return Response({
                    "message": str(e)
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # =========================
        # 🔐 LOCAL LOGIN FLOW
        # =========================
        elif login_method.lower() == "local":

            # find user by username OR email
            user_obj = User.objects.filter(
                Q(username=identifier) | Q(email=identifier)
            ).first()

            if user_obj is None:
                return Response({
                    "message": "Invalid credentials"
                }, status=status.HTTP_401_UNAUTHORIZED)

            # authenticate using username (Django requirement)
            user = authenticate(
                request,
                username=user_obj.username,
                password=password
            )

            if user is None:
                return Response({
                    "message": "Invalid credentials"
                }, status=status.HTTP_401_UNAUTHORIZED)

            refresh = RefreshToken.for_user(user)

            return Response({
                "message": "Local Login Successful",
                "refresh": str(refresh),
                "access": str(refresh.access_token),
                "uuid": str(user.uuid),
                "username": user.username,
                "department": getattr(user, "department", None),
                "email": user.email,
                "auth_source": "local"
            }, status=status.HTTP_200_OK)

        # =========================
        # ❌ INVALID METHOD
        # =========================
        else:
            return Response({
                "message": "Invalid login method. Use 'ldap' or 'local'"
            }, status=status.HTTP_400_BAD_REQUEST)
# class LoginAPIView(APIView):

#     def post(self, request):
#         username = request.data.get("username")
#         password = request.data.get("password")
#         login_method = request.data.get("loginMethod", "local")  # default local

#         if not username or not password:
#             return Response({
#                 "message": "Username and password are required"
#             }, status=status.HTTP_400_BAD_REQUEST)

#         # =========================
#         # 🔐 LDAP LOGIN FLOW
#         # =========================
#         if login_method.lower() == "ldap":
#             try:
#                 ldap_server = "ldap://192.168.0.4"

#                 conn = ldap.initialize(ldap_server)
#                 conn.protocol_version = 3
#                 conn.set_option(ldap.OPT_REFERRALS, 0)

#                 user_dn = f"{username}@madison.co.ke"

#                 # 🔐 Authenticate against AD
#                 conn.simple_bind_s(user_dn, password)

#                 # ✅ Create or get Django user
#                 user, created = User.objects.get_or_create(
#                     username=username,
#                     defaults={
#                         "email": f"{username}@madison.co.ke"
#                     }
#                 )

#                 refresh = RefreshToken.for_user(user)

#                 return Response({
#                     "message": "LDAP Login Successful",
#                     "refresh": str(refresh),
#                     "access": str(refresh.access_token),
#                     "uuid": str(user.uuid),
#                     "username": user.username,
#                     "department":user.department,
#                     "email": user.email,
#                     "auth_source": "ldap"
#                 }, status=status.HTTP_200_OK)

#             except ldap.INVALID_CREDENTIALS:
#                 return Response({
#                     "message": "Invalid LDAP credentials"
#                 }, status=status.HTTP_401_UNAUTHORIZED)

#             except ldap.SERVER_DOWN:
#                 return Response({
#                     "message": "LDAP server unavailable"
#                 }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

#             except Exception as e:
#                 return Response({
#                     "message": str(e)
#                 }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

#         # =========================
#         # 🔐 LOCAL LOGIN FLOW
#         # =========================
#         elif login_method.lower() == "local":
#             user = authenticate(request, username=username, password=password)

#             if user is None:
#                 return Response({
#                     "message": "Invalid local credentials"
#                 }, status=status.HTTP_401_UNAUTHORIZED)

#             refresh = RefreshToken.for_user(user)

#             return Response({
#                 "message": "Local Login Successful",
#                 "refresh": str(refresh),
#                 "access": str(refresh.access_token),
#                 "uuid": str(user.uuid),
#                 "username": user.username,
#                 "department":user.department,

#                 "email": user.email,
#                 "auth_source": "local"
#             }, status=status.HTTP_200_OK)

#         # =========================
#         # ❌ INVALID METHOD
#         # =========================
#         else:
#             return Response({
#                 "message": "Invalid login method. Use 'ldap' or 'local'"
#             }, status=status.HTTP_400_BAD_REQUEST)
            
            
            
# class LoginAPIView(APIView):

#     def post(self, request):

#         username = request.data.get("username")
#         password = request.data.get("password")

#         try:
#             ldap_server = "ldap://192.168.0.4"

#             conn = ldap.initialize(ldap_server)
#             conn.protocol_version = 3
#             conn.set_option(ldap.OPT_REFERRALS, 0)

#             # AD UPN format
#             user_dn = f"{username}@madison.co.ke"

#             # 🔐 LDAP AUTH (this is your real AD login)
#             conn.simple_bind_s(user_dn, password)

#             # ✅ If successful → get or create Django user
#             user, created = User.objects.get_or_create(
#                 username=username,
#                 defaults={
#                     "email": f"{username}@madison.co.ke"
#                 }
#             )

#             # 🔐 JWT generation
#             refresh = RefreshToken.for_user(user)

#             return Response({
#                 "message": "Login Successful",
#                 "refresh": str(refresh),
#                 "access": str(refresh.access_token),
#                 "uuid": str(user.uuid),
#                 "username": user.username,
#                 "email": user.email,
#                 "auth_source": "active-directory"
#             }, status=status.HTTP_200_OK)

#         except ldap.INVALID_CREDENTIALS:
#             return Response({
#                 "message": "Invalid credentials"
#             }, status=status.HTTP_401_UNAUTHORIZED)

#         except ldap.SERVER_DOWN:
#             return Response({
#                 "message": "Cannot connect to LDAP server"
#             }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

#         except Exception as e:
#             return Response({
#                 "message": str(e)
#             }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# class LoginAPIView(APIView):

#     def post(self, request):
#         serializer = LoginSerializer(
#             data=request.data,
#             context={"request": request}  # 🔥 important for LDAP auth flow
#         )
#         serializer.is_valid(raise_exception=True)

#         user = serializer.validated_data["user"]

#         # 🔐 JWT generation (same as before)
#         refresh = RefreshToken.for_user(user)

#         return Response({
#             "refresh": str(refresh),
#             "access": str(refresh.access_token),
#             "uuid": str(user.uuid),
#             "username": user.username,

#             # Optional but useful for AD debugging/visibility
#             "auth_source": "ldap-ad"
#         }, status=status.HTTP_200_OK)