function example()
% example  Connects this MATLAB session to the EEG_API_Unicorn engine with the settings of
% config.json, starts the mode, and prints every decision. Ctrl+C stops it: the mode it started
% is stopped and its streams are closed.
%
% Before running it: liblsl-Matlab on the path, e.g.
%     addpath(genpath('C:\path\to\liblsl-Matlab'));
% Then, in the console: "Connect an application", pick this application, then "Connect".
%
% To do something else with the decisions, change onDecision() below: the rest stays as it is.

here = fileparts(mfilename('fullpath'));
api = EegApi(EegApi.loadConfig(fullfile(here, 'config.json')));
cleanup = onCleanup(@() api.close()); %#ok<NASGU>   runs on Ctrl+C, on an error and at the end
api.connect();
api.start();
disp('Decisions arrive once the mode has warmed up and measured its rest: look at no target until then.');
while api.isConnected()
    decision = api.nextDecision(0.2);
    if ~isempty(decision)
        onDecision(decision);
    end
end
disp(api.whyDisconnected());
end

function onDecision(decision)
% A decision: the channels of the mode's decoded stream, by name (SSVEP target_index, freq_hz,
% confidence...). -1 means "no decision", never target 0.
if isfield(decision, 'target_index')
    index = decision.target_index;
elseif isfield(decision, 'intent_index')
    index = decision.intent_index;
else
    disp(decision);                 % neuro: no index, the values themselves
    return
end
if index >= 0
    fprintf('decoded: target %d (confidence %.2f)\n', round(index), decision.confidence);
end
end
