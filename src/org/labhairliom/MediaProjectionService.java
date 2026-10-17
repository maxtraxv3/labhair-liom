package org.labhairliom;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.IBinder;

/**
 * Minimal foreground service for MediaProjection on Android 14+.
 *
 * Runs in the main process (no android:process in manifest) so the system
 * accepts it for getMediaProjection(). p4a's PythonService runs in
 * ":python_service" (separate process), which causes SecurityException.
 */
public class MediaProjectionService extends Service {

    private static final String CHANNEL_ID = "labhairliom_bg";
    private static final int NOTIFICATION_ID = 9473;

    @Override
    public void onCreate() {
        super.onCreate();
        NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID, "Labhair-liom Chat", NotificationManager.IMPORTANCE_LOW);
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (nm != null) nm.createNotificationChannel(channel);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        Notification notification = new Notification.Builder(this, CHANNEL_ID)
                .setContentTitle("Labhair-liom Screen Share")
                .setContentText("Sharing screen")
                .setSmallIcon(0x0108009a)
                .setOngoing(true)
                .build();

        startForeground(NOTIFICATION_ID, notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION);
        return START_NOT_STICKY;
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public void onDestroy() {
        stopForeground(true);
        super.onDestroy();
    }
}
