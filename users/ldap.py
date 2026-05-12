
# ldap (python-ldap) is commented out because the package may not be installed.
# For LDAP operations prefer `ldap3` or re-enable python-ldap in your environment.
# import ldap
ldap = None
from django.shortcuts import render


from rest_framework.response import Response
from rest_framework import status


def ldap_login_test():
    username = "samuel.mwangangi"
    password = "Madison20263"

    try:
        ldap_server = "ldap://192.168.0.4"

        conn = ldap.initialize(ldap_server)
        conn.protocol_version = 3
        conn.set_option(ldap.OPT_REFERRALS, 0)

        # AD login format (UPN)
        user_dn = f"{username}@madison.co.ke"

        # LDAP bind
        conn.simple_bind_s(user_dn, password)

        return Response({
            "message": "✅ Login Successful",
            "username": username
        }, status=status.HTTP_200_OK)

    except ldap.INVALID_CREDENTIALS:
        return Response({
            "message": "❌ Invalid credentials"
        }, status=status.HTTP_401_UNAUTHORIZED)

    except ldap.SERVER_DOWN:
        return Response({
            "message": "❌ Cannot connect to LDAP server"
        }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    except Exception as e:
        return Response({
            "message": f"❌ Error: {str(e)}"
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

