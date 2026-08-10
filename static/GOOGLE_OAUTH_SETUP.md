# Guide de configuration des Clés Google OAuth2 (Client ID & Client Secret)

Ce guide décrit étape par étape comment configurer l'intégration de **Google Calendar** et **Google Contacts** dans l'application Immo-Boussole.

---

## Étape 1 : Créer un projet sur Google Cloud Console

1. Connectez-vous sur la [Google Cloud Console](https://console.cloud.google.com/).
2. En haut à gauche, cliquez sur le menu déroulant des projets et sélectionnez **Nouveau Projet**.
3. Saisissez un nom pour votre projet (par exemple, `Immo-Boussole`) et cliquez sur **Créer**.

---

## Étape 2 : Activer les API Google Calendar & Google People (Contacts)

1. Dans le menu de gauche, accédez à **API et services** > **Bibliothèque**.
2. Recherchez **Google Calendar API**, cliquez dessus, puis cliquez sur **Activer**.
3. Revenez à la Bibliothèque, recherchez **Google People API**, cliquez dessus, puis cliquez sur **Activer**.

---

## Étape 3 : Configurer l'écran de consentement OAuth

Avant de générer des clés, vous devez configurer les informations présentées à l'utilisateur lors de la connexion.

1. Allez dans **API et services** > **Écran de consentement OAuth**.
2. Choisissez le type d'utilisateur :
   - **Interne** (si vous utilisez Google Workspace au sein d'une organisation).
   - **Externe** (si vous utilisez un compte Gmail classique `@gmail.com`). Sélectionnez **Externe** et cliquez sur **Créer**.
3. Remplissez les informations obligatoires :
   - **Nom de l'application** : `Immo-Boussole`
   - **Adresse e-mail d'assistance utilisateur** : Votre e-mail.
   - **Coordonnées de développeur** : Votre e-mail.
4. Cliquez sur **Enregistrer et continuer** pour passer les sections « Champs d'application » (Scopes) et « Utilisateurs de test ».
5. **Important (si Externe) :** Dans l'onglet **Utilisateurs de test**, ajoutez l'adresse e-mail du compte Google avec lequel vous souhaitez vous synchroniser (ex. `GOOGLE_ACCOUNT_EMAIL@gmail.com` ou l'adresse e-mail pilote configurée dans l'application).

---

## Étape 4 : Créer les Identifiants OAuth 2.0

1. Allez dans **API et services** > **Identifiants**.
2. Cliquez sur **Créer des identifiants** en haut de l'écran, puis sélectionnez **ID de client OAuth**.
3. Dans la liste déroulante **Type d'application**, sélectionnez **Application Web**.
4. Remplissez le formulaire :
   - **Nom** : `Immo-Boussole Web Client`
   - **Origines JavaScript autorisées** :
     Ajoutez les URL de base de votre application :
     - `https://YOUR_APP_DOMAIN.com` (pour votre serveur de dev)
     - `http://localhost:8000` (pour un développement en local)
   - **URI de redirection autorisés** :
     Ajoutez les URL de callback complètes de l'application :
     - `https://YOUR_APP_DOMAIN.com/api/auth/google/callback`
     - `https://YOUR_APP_DOMAIN.com/api/v1/auth/google/callback`
     - `http://localhost:8000/api/auth/google/callback`
     - `http://localhost:8000/api/v1/auth/google/callback`
5. Cliquez sur **Créer**.

---

## Étape 5 : Télécharger et configurer les clés dans Immo-Boussole

Une fois le client OAuth créé, une fenêtre contextuelle s'ouvre avec votre **ID client** et votre **Code secret du client**.

Vous avez deux façons de renseigner ces clés dans l'interface de maintenance d'Immo-Boussole (`/admin/maintenance`) :

### Option A : Renseigner les champs individuels (Simple)
- Copiez la valeur de **ID client** et collez-la dans le champ **Google Client ID** de l'application.
- Copiez la valeur de **Code secret du client** et collez-la dans le champ **Google Client Secret** de l'application.
- Cliquez sur **Enregistrer les clés**.

### Option B : Coller le fichier JSON (Recommandé)
1. Dans l'écran des identifiants Google Cloud Console, en face de votre client OAuth Web nouvellement créé, cliquez sur l'icône de téléchargement **Télécharger le fichier JSON**.
2. Ouvrez le fichier téléchargé (généralement nommé `client_secret_xxxxxx.json`) avec un éditeur de texte.
3. Copiez l'intégralité de son contenu.
4. Collez-le dans la zone de texte **OU coller directement le contenu du fichier credentials.json** de l'application.
5. Cliquez sur **Enregistrer les clés**.
