package com.dusu.app

import android.app.AlarmManager
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import com.google.androidbrowserhelper.trusted.TwaLauncher
import java.io.File

/**
 * Entry activity:
 *   1) Offline → show a "turn on the internet" screen (Retry re-checks).
 *   2) Online  → launch the Trusted Web Activity via TwaLauncher (site runs inside the
 *      app on Chrome's engine, so Web Speech mic/voice works).
 * Notifications are NOT sent from here: DuSu's reminders and nudges are web-push messages from
 * the server that Chrome hands to DelegationService (see the manifest), so they are personal and
 * the learner controls them inside the app. This activity also captures any uncaught crash to a
 * file so it can be shown on the next launch (diagnostics without a USB cable).
 */
class MainActivity : android.app.Activity() {

    private lateinit var splashView: View
    private lateinit var offlineView: View
    private var twaLauncher: TwaLauncher? = null
    private var launched = false

    private fun crashFile() = File(filesDir, "last_crash.txt")

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Capture any uncaught crash (this activity OR the TWA, same process) to a file.
        val prev = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { t, e ->
            try {
                crashFile().writeText(
                    "DuSu crash\n" + android.util.Log.getStackTraceString(e)
                )
            } catch (_: Throwable) {}
            prev?.uncaughtException(t, e)
        }

        // If the last run crashed, show the trace instead of launching (screenshot it to us).
        if (crashFile().exists()) {
            showCrash(crashFile().readText())
            return
        }

        setContentView(R.layout.activity_main)
        splashView = findViewById(R.id.splashView)
        offlineView = findViewById(R.id.offlineView)
        findViewById<Button>(R.id.retryBtn).setOnClickListener { decide() }

        cancelLegacyReminders()

        Handler(Looper.getMainLooper()).postDelayed({
            if (!isFinishing) { splashView.visibility = View.GONE; decide() }
        }, 1200)
    }

    override fun onResume() {
        super.onResume()
        if (launched) { finish(); return }   // returned from the TWA → close the shim
    }

    override fun onDestroy() {
        twaLauncher?.destroy()
        super.onDestroy()
    }

    private fun decide() {
        if (isOnline()) {
            offlineView.visibility = View.GONE
            launchDuSu()
        } else {
            offlineView.visibility = View.VISIBLE
        }
    }

    private fun launchDuSu() {
        if (launched) return
        launched = true
        try {
            val url = Uri.parse(getString(R.string.launchUrl))
            twaLauncher = TwaLauncher(this)
            twaLauncher!!.launch(url)
        } catch (e: Throwable) {
            launched = false
            showCrash("Could not launch DuSu:\n" + android.util.Log.getStackTraceString(e))
        }
    }

    private fun isOnline(): Boolean {
        return try {
            val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
            val net = cm.activeNetwork ?: return false
            val caps = cm.getNetworkCapabilities(net) ?: return false
            caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
        } catch (_: Throwable) {
            true   // if we can't tell, don't block the user
        }
    }

    /**
     * Version 1.0 fired the same "practise English" message every 4 hours from an AlarmManager alarm.
     * That is gone, but an installed copy may still have the alarm armed (and its notification channel
     * listed in Android settings), so remove both. The old receiver class no longer exists, so the
     * PendingIntent is looked up by class name (FLAG_NO_CREATE = find it, never make one).
     */
    private fun cancelLegacyReminders() {
        try {
            val old = PendingIntent.getBroadcast(
                this, 0, Intent().setClassName(packageName, "$packageName.ReminderReceiver"),
                PendingIntent.FLAG_NO_CREATE or PendingIntent.FLAG_IMMUTABLE
            )
            if (old != null) {
                (getSystemService(Context.ALARM_SERVICE) as AlarmManager).cancel(old)
                old.cancel()
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                (getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager)
                    .deleteNotificationChannel("dusu_reminders")
            }
        } catch (_: Throwable) {
            // best effort - a failure here must never stop DuSu from opening
        }
    }

    /** Minimal scrollable error screen so a crash is visible without adb. */
    private fun showCrash(text: String) {
        val tv = TextView(this).apply {
            setText(text)
            setTextColor(Color.WHITE)
            setPadding(32, 48, 32, 32)
            textSize = 12f
            setTextIsSelectable(true)
        }
        val btn = Button(this).apply {
            setText("Clear & retry")
            setOnClickListener { crashFile().delete(); recreate() }
        }
        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.parseColor("#070A14"))
            addView(btn)
            addView(tv)
        }
        setContentView(ScrollView(this).apply { addView(col) })
    }
}
