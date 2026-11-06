using System;
using System.IO;
using LSL;
using UnityEditor;
using UnityEngine;

/// <summary>
/// Plays the whole handshake of EegApiLink against a running engine, with the settings of
/// Assets/StreamingAssets/eeg_api_config.json, without a scene, and exits with code 0 when every
/// step got the expected reply, 1 otherwise (the log says which step):
///
///     python src/core/server.py --synthetic
///     Unity.exe -batchmode -projectPath &lt;this project&gt; -executeMethod EegApiSelfTest.Run -logFile -
///
/// `server.py` alone listens to the applications of its own computer at once: no click is needed.
/// With the console, click "Connect an application" and pick "unity-selftest-…" within 60 s.
/// This file belongs in an Editor folder: it is not part of a built application.
/// </summary>
public static class EegApiSelfTest
{
    public static void Run()
    {
        int code = 1;
        try
        {
            code = Play();
        }
        catch (Exception e)
        {
            Debug.LogError("[selftest] " + e);
        }
        EditorApplication.Exit(code);
    }

    static int Play()
    {
        EegApiConfig config = EegApiConfig.Load(Path.Combine(Application.streamingAssetsPath, "eeg_api_config.json"));
        if (string.IsNullOrEmpty(config.mode) || config.ParamsJson == null || !config.ParamsJson.StartsWith("{")
            || !config.ParamsJson.TrimEnd().EndsWith("}"))
            return Fail("eeg_api_config.json: mode or params not read (" + config.ParamsJson + ")");
        Debug.Log("[selftest] config: mode=" + config.mode + " params=" + config.ParamsJson);
        string mode = config.mode;
        using (var link = new EegApiLink("unity-selftest", m => Debug.Log("[selftest] " + m)))
        {
            if (!link.Connect(60.0, () => false))
                return Fail("no engine connected us within 60 s");
            string settings = config.ParamsJson;
            double refresh = config.propose_refresh_hz < 0 ? 60 : config.propose_refresh_hz;
            if (refresh > 0)
            {
                EngineReply proposed = link.Send("propose_params", mode, "{\"refresh_hz\": " + Json.Number(refresh) + "}");
                if (proposed == null || !proposed.accepted || proposed.value == null || proposed.value.Length == 0)
                    return Fail("propose_params");
                settings = settings.TrimEnd().TrimEnd('}') + ", \"refresh_hz\": " + Json.Number(refresh)
                           + ", \"" + proposed.key + "\": " + Json.Numbers(proposed.value) + "}";
            }
            EngineReply set = link.Send("set_params", mode, settings);
            if (set == null || !set.accepted)
                return Fail("set_params: " + (set != null ? set.reason : "no reply"));
            EngineReply start = link.Send("start_mode", mode);
            if (start == null || !start.accepted)
                return Fail("start_mode");
            DateTime deadline = DateTime.UtcNow.AddSeconds(90);
            StreamInlet decoded = link.OpenDecoded(mode, () => DateTime.UtcNow > deadline, out string[] labels);
            if (decoded == null)
                return Fail("the decoded stream of our engine did not appear");
            Debug.Log("[selftest] channels: " + string.Join(", ", labels));
            if (Array.IndexOf(labels, "target_index") < 0 && Array.IndexOf(labels, "intent_index") < 0)
                return Fail("no target_index or intent_index channel");
            var sample = new float[labels.Length];
            int got = 0;
            while (got < 3 && DateTime.UtcNow < deadline)
            {
                if (decoded.pull_sample(sample, 0.5) != 0.0)
                {
                    got++;
                    Debug.Log("[selftest] decision " + got + ": " + labels[0] + "=" + sample[0]
                              + (sample[0] < 0 ? " (-1 = no decision)" : ""));
                }
                if (!link.Connected())
                    return Fail(link.WhyDisconnected());
            }
            decoded.Dispose();
            if (got < 3)
                return Fail("only " + got + " decision(s) in 90 s");
            if (!start.already_running)
            {
                EngineReply stop = link.Send("stop_mode", mode);
                if (stop == null || !stop.accepted)
                    return Fail("stop_mode");
            }
            Debug.Log("[selftest] OK: every step got the expected reply (" + got + " decisions)");
            return 0;
        }
    }

    static int Fail(string why)
    {
        Debug.LogError("[selftest] FAILED: " + why);
        return 1;
    }
}
