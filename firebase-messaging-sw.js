// Loaded only by the student after they explicitly enable background reminders.
// Firebase configuration values are public web-app identifiers; server secrets
// and the student's device identifier never appear in this file.
const FIREBASE_WEB_SDK_VERSION = '12.1.0';

async function initialiseMessaging() {
  const response = await fetch('/api/integrations/firebase-config', { cache: 'no-store' });
  if (!response.ok) return null;
  const config = await response.json();
  const [firebaseApp, firebaseMessaging] = await Promise.all([
    import(`https://www.gstatic.com/firebasejs/${FIREBASE_WEB_SDK_VERSION}/firebase-app.js`),
    import(`https://www.gstatic.com/firebasejs/${FIREBASE_WEB_SDK_VERSION}/firebase-messaging-sw.js`)
  ]);
  const app = firebaseApp.getApps().length ? firebaseApp.getApp() : firebaseApp.initializeApp(config);
  const messaging = firebaseMessaging.getMessaging(app);
  firebaseMessaging.onBackgroundMessage(messaging, payload => {
    const body = String(payload?.notification?.body || 'Your planned Equilibrium reminder is ready.').slice(0, 180);
    self.registration.showNotification('Equilibrium', {
      body,
      icon: '/favicon.ico',
      data: { destination: '/' }
    });
  });
  return messaging;
}

initialiseMessaging().catch(() => {
  // The page explains setup state; do not expose configuration or identifiers in logs.
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil(clients.openWindow(event.notification.data?.destination || '/'));
});
