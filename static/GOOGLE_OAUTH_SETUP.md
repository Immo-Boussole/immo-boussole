# Google OAuth2 Credentials Setup Guide (Client ID & Client Secret)

This guide walks you through setting up the **Google Calendar** and **Google Contacts** integrations in the application.

---

## Step 1: Create a Project on Google Cloud Console

1. Log in to the [Google Cloud Console](https://console.cloud.google.com/).
2. In the top-left corner, click the project selection dropdown and select **New Project**.
3. Enter a name for your project (e.g., `Immo-Boussole`) and click **Create**.

---

## Step 2: Enable the Google Calendar & Google People (Contacts) APIs

1. In the left navigation menu, go to **APIs & Services** > **Library**.
2. Search for **Google Calendar API**, click on it, and click **Enable**.
3. Go back to the Library, search for **Google People API**, click on it, and click **Enable**.

---

## Step 3: Configure the OAuth Consent Screen

Before generating credentials, you must configure the screen shown to users during authentication.

1. Go to **APIs & Services** > **OAuth Consent Screen**.
2. Select the User Type:
   - **Internal**: If you are using Google Workspace within an organization.
   - **External**: If you are using a standard `@gmail.com` personal account. Select **External** and click **Create**.
3. Fill in the required fields:
   - **App name**: `Immo-Boussole`
   - **User support email**: Select your email address.
   - **Developer contact information**: Enter your email address.
4. Click **Save and Continue** to skip the "Scopes" section.
5. **Important (if External):** In the **Test users** tab, add the email address of the Google account you wish to synchronize (e.g., the pilot email address configured in the application). Click **Save and Continue**.

---

## Step 4: Create OAuth 2.0 Credentials

1. Go to **APIs & Services** > **Credentials**.
2. Click **Create Credentials** at the top, then select **OAuth Client ID**.
3. Under the **Application type** dropdown, select **Web Application**.
4. Fill out the form:
   - **Name**: `Immo-Boussole Web Client`
   - **Authorized JavaScript origins**:
     Add the base URL(s) of your application instance:
     - `https://your-domain.com` (replace with your actual server domain name)
     - `http://localhost:8000` (for local development)
   - **Authorized redirect URIs**:
     Add the complete callback URL(s) of your application instance:
     - `https://your-domain.com/api/auth/google/callback` (replace with your actual server domain name)
     - `https://your-domain.com/api/v1/auth/google/callback`
     - `http://localhost:8000/api/auth/google/callback`
     - `http://localhost:8000/api/v1/auth/google/callback`
5. Click **Create**.

---

## Step 5: Save Credentials in the Application

Once the OAuth client is created, a modal will display your **Client ID** and **Client Secret**.

You can save these credentials in the application's maintenance page (`/admin/maintenance`) in one of two ways:

### Option A: Enter the Keys Manually
- Copy the **Client ID** value and paste it into the **Google Client ID** field.
- Copy the **Client Secret** value and paste it into the **Google Client Secret** field.
- Click **Enregistrer les clés** (Save Keys).

### Option B: Paste the credentials.json File Content (Recommended)
1. In the Google Cloud Console credentials page, click the download icon **Download JSON** for your Web client.
2. Open the downloaded JSON file (usually named `client_secret_xxxxxx.json`) in a text editor.
3. Copy the entire file content.
4. Paste it into the text area labeled **OU coller directement le contenu du fichier credentials.json** in the application.
5. Click **Enregistrer les clés** (Save Keys).
