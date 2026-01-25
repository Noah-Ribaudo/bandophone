package com.bandophone

import android.app.Application
import android.util.Log

class BandophoneApp : Application() {
    companion object {
        const val TAG = "Bandophone"
        lateinit var instance: BandophoneApp
            private set
    }

    override fun onCreate() {
        super.onCreate()
        instance = this
        Log.d(TAG, "Bandophone started")
    }
}
