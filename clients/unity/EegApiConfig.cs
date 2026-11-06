using System;
using System.IO;
using UnityEngine;

/// <summary>
/// The settings of the connection, read from a JSON file (by default
/// Assets/StreamingAssets/eeg_api_config.json). Do not edit this class: edit the file.
///
///     {
///       "app_name": "my-game",          the name the console lists under "Connect an application"
///       "mode": "ssvep",                ssvep, mi, neuro, p300, errp, cvep
///       "params": { ... },              the settings of the mode, sent as they are (docs/control.md)
///       "propose_refresh_hz": -1,       SSVEP on a screen: ask the engine for frequencies that
///                                       divide this refresh rate; -1 = this screen's, 0 = do not ask
///       "stop_mode_on_exit": true,
///       "search_timeout_s": 30
///     }
/// </summary>
[Serializable]
public class EegApiConfig
{
    public string app_name = "my-game";
    public string mode = "ssvep";
    public double propose_refresh_hz = 0;
    public bool stop_mode_on_exit = true;
    public float search_timeout_s = 30f;

    /// <summary>The "params" object of the file, as JSON text, or null when there is none.</summary>
    [NonSerialized] public string ParamsJson;

    public static EegApiConfig Load(string path)
    {
        string text = File.ReadAllText(path);
        EegApiConfig config = JsonUtility.FromJson<EegApiConfig>(text);
        config.ParamsJson = RawValue(text, "params");
        return config;
    }

    /// <summary>
    /// The JSON text of a top-level key, as written in the file. JsonUtility cannot read an object
    /// whose keys are not known in advance; the engine reads it, so it is forwarded unchanged.
    /// </summary>
    public static string RawValue(string json, string key)
    {
        int depth = 0;
        for (int i = 0; i < json.Length; i++)
        {
            char c = json[i];
            if (c == '"')
            {
                int end = EndOfString(json, i);
                if (depth == 1 && json.Substring(i + 1, end - i - 1) == key)
                {
                    int colon = json.IndexOf(':', end);
                    int start = colon + 1;
                    while (start < json.Length && char.IsWhiteSpace(json[start]))
                        start++;
                    return json.Substring(start, EndOfValue(json, start) - start);
                }
                i = end;
            }
            else if (c == '{' || c == '[') depth++;
            else if (c == '}' || c == ']') depth--;
        }
        return null;
    }

    static int EndOfString(string json, int quote)
    {
        for (int i = quote + 1; i < json.Length; i++)
        {
            if (json[i] == '\\') i++;
            else if (json[i] == '"') return i;
        }
        throw new FormatException("unterminated string in the configuration file");
    }

    static int EndOfValue(string json, int start)
    {
        int depth = 0;
        for (int i = start; i < json.Length; i++)
        {
            char c = json[i];
            if (c == '"')
            {
                i = EndOfString(json, i);
                if (depth == 0) return i + 1;
            }
            else if (c == '{' || c == '[') depth++;
            else if (c == '}' || c == ']')
            {
                if (depth == 0) return i;
                if (--depth == 0) return i + 1;
            }
            else if (depth == 0 && (c == ',' || char.IsWhiteSpace(c))) return i;
        }
        return json.Length;
    }
}
