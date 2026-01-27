package com.bandophone

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/**
 * Secure storage for OpenAI API key using EncryptedSharedPreferences
 */
object ApiKeyManager {
    private const val PREFS_NAME = "bandophone_secure_prefs"
    private const val KEY_OPENAI_API_KEY = "openai_api_key"
    private const val KEY_AI_INSTRUCTIONS = "ai_instructions"
    private const val KEY_AI_VOICE = "ai_voice"
    private const val KEY_GATEWAY_URL = "gateway_url"
    
    private const val DEFAULT_GATEWAY_URL = "http://192.168.4.82:3000"  // Mac mini Tailscale
    
    private const val DEFAULT_INSTRUCTIONS = """
        You are a helpful AI assistant on a phone call.
        Be conversational, natural, and concise.
        Listen carefully and respond appropriately.
        If interrupted, stop speaking immediately.
    """
    
    private fun getEncryptedPrefs(context: Context): SharedPreferences {
        val masterKey = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        
        return EncryptedSharedPreferences.create(
            context,
            PREFS_NAME,
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
        )
    }
    
    fun saveApiKey(context: Context, apiKey: String) {
        getEncryptedPrefs(context).edit()
            .putString(KEY_OPENAI_API_KEY, apiKey.trim())
            .apply()
    }
    
    fun getApiKey(context: Context): String? {
        return getEncryptedPrefs(context).getString(KEY_OPENAI_API_KEY, null)?.trim()
    }
    
    fun hasApiKey(context: Context): Boolean {
        return !getApiKey(context).isNullOrBlank()
    }
    
    fun saveInstructions(context: Context, instructions: String) {
        getEncryptedPrefs(context).edit()
            .putString(KEY_AI_INSTRUCTIONS, instructions)
            .apply()
    }
    
    fun getInstructions(context: Context): String {
        return getEncryptedPrefs(context).getString(KEY_AI_INSTRUCTIONS, DEFAULT_INSTRUCTIONS)
            ?: DEFAULT_INSTRUCTIONS
    }
    
    fun saveVoice(context: Context, voice: String) {
        getEncryptedPrefs(context).edit()
            .putString(KEY_AI_VOICE, voice)
            .apply()
    }
    
    fun getVoice(context: Context): String {
        return getEncryptedPrefs(context).getString(KEY_AI_VOICE, "alloy") ?: "alloy"
    }
    
    fun clearApiKey(context: Context) {
        getEncryptedPrefs(context).edit()
            .remove(KEY_OPENAI_API_KEY)
            .apply()
    }
    
    fun saveGatewayUrl(context: Context, url: String) {
        getEncryptedPrefs(context).edit()
            .putString(KEY_GATEWAY_URL, url.trim())
            .apply()
    }
    
    fun getGatewayUrl(context: Context): String {
        return getEncryptedPrefs(context).getString(KEY_GATEWAY_URL, DEFAULT_GATEWAY_URL)
            ?: DEFAULT_GATEWAY_URL
    }
}
