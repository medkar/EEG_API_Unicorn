using UnityEngine;

/// <summary>
/// Turns a decoded intent into something happening on screen.
///
/// This file is the point of the whole example. The API told us *which target the user is
/// looking at*; deciding that target 0 means "move forward" is a choice that belongs here,
/// in your application, not in the EEG engine. Swap this script and the same brain signal
/// drives a menu, a wheelchair or a synthesiser -- with no change on the engine side.
///
/// Attach next to SsvepIntentReceiver and assign a Transform to move.
/// </summary>
[RequireComponent(typeof(SsvepIntentReceiver))]
public class IntentToMotion : MonoBehaviour
{
    [Tooltip("Object driven by the decoded intent.")]
    public Transform target;

    [Tooltip("Metres per second while an intent is held.")]
    public float speed = 1.5f;

    [Tooltip("Direction for each target index, in the order the engine declares its frequencies.")]
    public Vector3[] directions =
    {
        Vector3.forward,   // target 0
        Vector3.left,      // target 1
        Vector3.right,     // target 2
    };

    private SsvepIntentReceiver eeg;

    private void Awake()
    {
        eeg = GetComponent<SsvepIntentReceiver>();
    }

    private void Update()
    {
        if (target == null) return;

        int index = eeg.TargetIndex;

        // -1 means the engine saw nothing convincing: no target above its threshold, or a
        // window rejected as an artefact (a blink, a jaw clench). Treat it as "stop", never
        // as "keep doing whatever you were doing" -- an artefact must not sustain motion.
        if (index < 0 || index >= directions.Length) return;

        target.Translate(directions[index] * speed * Time.deltaTime, Space.World);
    }

    private void OnGUI()
    {
        // Minimal on-screen feedback. Seeing the confidence next to the decision is what
        // tells a missed detection from an absent signal when nothing seems to happen.
        string label = eeg.TargetIndex < 0
            ? "no target"
            : $"target {eeg.TargetIndex} @ {eeg.FrequencyHz:0.##} Hz";
        GUI.Label(new Rect(12, 12, 420, 22),
                  $"{label}   confidence {eeg.Confidence:0.00} ({eeg.DecisionScale})");
    }
}
