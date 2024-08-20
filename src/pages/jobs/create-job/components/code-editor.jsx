import React,{useState,useEffect} from "react";
import 'ace-builds/css/ace.css';
import 'ace-builds/css/theme/cloud_editor.css';
import 'ace-builds/css/theme/cloud_editor_dark.css';
import {
  CodeEditor
} from "@cloudscape-design/components";

export const JsonEditor = (props) =>{
    const [preferences, setPreferences] = useState(
      undefined
    );
    const [ace, setAce] = useState();
    const [loading, setLoading] = useState(true);
    // console.log(props)
    useEffect(() => {
      async function loadAce() {
        const ace = await import('ace-builds');
        await import('ace-builds/webpack-resolver');
        ace.config.set('useStrictCSP', true);
        return ace;
      }
  
      loadAce()
        .then(ace => setAce(ace))
        .finally(() => setLoading(false));
    }, []);
    return <CodeEditor 
           {...props}
           preferences={preferences}
           onPreferencesChange={e => setPreferences(e.detail)}
            loading={loading}
            ace={ace}
            language="json"
            themes={{
                light: ["cloud_editor"],
                dark: ["cloud_editor_dark"]
              }}
  />
  }