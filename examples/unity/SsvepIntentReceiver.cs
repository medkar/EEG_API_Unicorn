using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Events;
using LSL;

/// <summary>
/// Receives the decoded SSVEP intent from EEG_API_Unicorn and exposes it to your scene.
///
/// This component does one job: turn the network stream into a C# value. It deliberately
/// does NOT move, rotate or trigger anything -- see IntentToMotion for that. The API
/// publishes an *intent* ("the user is looking at target 2"), never an actuator command,
/// which is exactly what lets the same stream drive a game, a visualisation or a robot.
///
/// Drop this on any GameObject. Nothing else is required: the engine is a separate process,
/// possibly on another machine.
/// </summary>
public class SsvepIntentReceiver : MonoBehaviour
{
    [Tooltip("Stream name published by the engine. Must match src/core/lsl_io.py.")]
    public string streamName = "EEG_API_Unicorn_decoded_ssvep";

    [Tooltip("Engine instance to attach to (headset serial). Leave empty to take the first one found.")]
    public string instanceId = "";

    /// <summary>Index of the target being looked at, or -1 when none is reliable.</summary>
    public int TargetIndex { get; private set; } = -1;

    /// <summary>Flicker frequency of that target in Hz, 0 when none.</summary>
    public float FrequencyHz { get; private set; }

    /// <summary>
    /// Score of the winning target on the scale the engine announces in its metadata
    /// (see DecisionScale). Do not compare it against a threshold of your own without
    /// reading that scale first -- "2.5" means nothing until you know it is a z-score.
    /// </summary>
    public float Confidence { get; private set; }

    /// <summary>"z" once the engine has measured its rest floor. Read from stream metadata.</summary>
    public string DecisionScale { get; private set; } = "unknown";

    /// <summary>
    /// Timestamp of the last decision, in THIS machine's LSL clock (time_correction applied).
    /// Not needed to move a cube; needed the moment you want to score a session, because the
    /// stimulus programs stamp their cues on that same clock and the two files join on it.
    /// </summary>
    public double LastTimestamp { get; private set; }

    /// <summary>
    /// Seconds since the last decision arrived, or a large number before the first one.
    /// The engine speaks ~5 times a second while decoding, so anything above ~1 s means the
    /// stream went quiet -- engine stopped, network dropped, mode switched off. Silence is NOT
    /// an intent: this is what lets a consumer stop instead of coasting on a stale value.
    /// </summary>
    public float SecondsSinceLastDecision => Time.time - lastSampleAt;

    /// <summary>
    /// Fires only when the selected target changes, including changes to -1.
    /// The named subclass is what makes it appear in the Inspector -- a bare
    /// UnityEvent&lt;int&gt; field compiles but Unity will not serialise it.
    /// </summary>
    [System.Serializable] public class TargetChangedEvent : UnityEvent<int> { }
    public TargetChangedEvent OnTargetChanged = new TargetChangedEvent();

    private StreamInlet inlet;
    private float[] sample;
    private int nTargets;
    private double clockOffset;
    private float lastSampleAt = -999f;

    private void Start()
    {
        StartCoroutine(Connect());
    }

    private IEnumerator Connect()
    {
        while (inlet == null)
        {
            // Short timeout: resolve_stream blocks the calling thread, so a long one would
            // stall the frame. Retrying once a second costs nothing and lets the scene run
            // before the engine is even started.
            //
            // `LSL.LSL` is not a typo. LSL4Unity puts a static class named `LSL` inside a
            // namespace also named `LSL`, so a bare `LSL.resolve_stream` binds to the NAMESPACE
            // and does not compile. LSL4Unity's own code writes `LSL.LSL.local_clock()` for the
            // same reason (Runtime/Scripts/TimeSync.cs).
            StreamInfo[] found = LSL.LSL.resolve_stream("name", streamName, 1, 0.2);

            if (found.Length > 0)
            {
                StreamInfo chosen = Pick(found);
                if (chosen != null)
                {
                    // A whole classroom may run engines on one network. Each publishes the
                    // same stream name, so without an instance id you may well connect to a
                    // classmate's headset -- and nothing would look wrong.
                    // Count distinct source ids: a machine with several network interfaces
                    // answers once per interface, so the same engine comes back two or three
                    // times and a naive count would warn on every normal setup.
                    var ids = new HashSet<string>();
                    foreach (StreamInfo info in found) ids.Add(info.source_id());
                    if (ids.Count > 1 && string.IsNullOrEmpty(instanceId))
                    {
                        Debug.LogWarning($"[EEG] {ids.Count} engines publish '{streamName}'. " +
                                         "Set instanceId to your own headset serial.");
                    }

                    inlet = new StreamInlet(chosen);
                    // Connect before the interesting data arrives. An inlet only connects on
                    // its first pull and LSL never replays what was sent before you attached.
                    inlet.open_stream(5.0);

                    ReadMetadata();
                    // Offset between the engine's clock and ours. Zero on one machine; several
                    // WEEKS across two, because local_clock() counts from each machine's boot.
                    clockOffset = inlet.time_correction(5.0);
                    Debug.Log($"[EEG] connected to {chosen.source_id()} — " +
                              $"{nTargets} targets, decision scale '{DecisionScale}', " +
                              $"clock offset {clockOffset * 1000.0:0.###} ms");
                    yield break;
                }
            }
            yield return new WaitForSeconds(1.0f);
        }
    }

    private StreamInfo Pick(StreamInfo[] found)
    {
        if (string.IsNullOrEmpty(instanceId)) return found[0];
        foreach (StreamInfo info in found)
        {
            if (info.source_id().Contains(instanceId)) return info;
        }
        Debug.LogWarning($"[EEG] no engine matching instance '{instanceId}' yet.");
        return null;
    }

    private void ReadMetadata()
    {
        // Keep `info` referenced for as long as anything read out of it is still in use. An
        // XMLElement holds a raw pointer into the StreamInfo's XML document and owns nothing:
        // let the StreamInfo be collected first and you are reading freed memory. Measured on
        // the Python side of this project, where it looked like a flaky test for weeks.
        StreamInfo info = inlet.info();

        // Channel layout is target_index, freq_hz, confidence, then one score per target.
        // Deriving the target count from the channel count rather than hardcoding it means
        // the scene keeps working when the engine is started with a different --freqs.
        nTargets = info.channel_count() - 3;
        sample = new float[info.channel_count()];

        // child_value returns an empty string when the node is missing, so no emptiness
        // test is needed -- one less API surface to get wrong across package versions.
        string scale = info.desc().child("decoding").child_value("decision_scale");
        if (!string.IsNullOrEmpty(scale)) DecisionScale = scale;
    }

    private void Update()
    {
        if (inlet == null) return;

        // Drain everything queued since the last frame; keep only the most recent decision.
        // The engine decodes at ~5 Hz while Unity runs far faster, so most frames pull
        // nothing at all -- that is expected, not an error.
        double stamp = 0.0, last = 0.0;
        while ((stamp = inlet.pull_sample(sample, 0.0)) != 0.0) last = stamp;
        if (last == 0.0) return;

        LastTimestamp = last + clockOffset;
        lastSampleAt = Time.time;

        int target = Mathf.RoundToInt(sample[0]);
        FrequencyHz = sample[1];
        Confidence = sample[2];

        if (target != TargetIndex)
        {
            TargetIndex = target;
            OnTargetChanged.Invoke(target);
        }
    }

    /// <summary>Per-target scores, in the order the engine declared its frequencies.</summary>
    public IEnumerable<float> Scores()
    {
        // Empty rather than throwing: a scene can call this before the engine is up, and a
        // NullReferenceException in someone else's Update is a bad way to learn that.
        if (sample == null) yield break;
        for (int i = 0; i < nTargets; i++) yield return sample[3 + i];
    }

    private void OnDestroy()
    {
        if (inlet != null)
        {
            inlet.close_stream();
            // StreamInlet is a SafeHandle: Dispose releases the native inlet now instead of
            // whenever the finaliser gets round to it. Entering Play mode repeatedly without
            // this leaves one live inlet per run.
            inlet.Dispose();
            inlet = null;
        }
    }
}
