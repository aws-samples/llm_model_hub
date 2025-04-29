// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { useEffect, useState,useCallback,useRef } from 'react';
import { remotePost } from '../../../../common/api-gateway';
import Textarea from "@cloudscape-design/components/textarea";
import FormField from "@cloudscape-design/components/form-field";
import Button from "@cloudscape-design/components/button";
import Container  from '@cloudscape-design/components/container';
import Header from "@cloudscape-design/components/header";
import Badge from "@cloudscape-design/components/badge";
import {JOB_STATE} from "../../table-config";
const defaultRows = 20;
const defaultMaxRows = 50;
export const LogsPanel = ({jobRunName,jobId,jobStatus}) => {
    const [logs, setLogs] = useState(['Start running, please wait a few minutes...']);
    const [loading, setLoading] = useState(false);
    const [rows, setRows] = useState(defaultRows);
    const [stopRefresh,setStop] = useState(false);
    const [newJobStatus, setNewStatus] = useState(jobStatus);
    const intervalRef = useRef(null);
    const intervalRef2 = useRef(null);
    const nextTokenRef = useRef(null);
    // const [nextToken,setNextToken] = useState(null);

    function sortEventsByTimestamp(events) {
        return events.sort((a, b) => {
            // 从每个字符串中提取时间戳
            const timestampA = new Date(a.split(': ')[0]);
            const timestampB = new Date(b.split(': ')[0]);
            
            // 比较时间戳
            return timestampA - timestampB;
        });
    }
    const fetchLogs = async () => {
        setLoading(true);
        let params = {
            "next_token": nextTokenRef.current,
            'job_id':jobId};
        let stop = false
        while (!stop)
            try {
                const res = await remotePost(params, 'fetch_training_log');
                setLoading(false);
                console.log('logs:',res.next_forward_token);
                stop = (res.next_forward_token === params.next_token)?true:false;
                nextTokenRef.current = res.next_forward_token
                params.next_token = res.next_forward_token;
                if (res.log_events.length ){
                    setLogs((prev) => prev.concat(sortEventsByTimestamp(res.log_events)));
                    setRows(logs.length > defaultRows ?
                        (logs.length > defaultMaxRows ? defaultMaxRows :logs.length) : defaultRows);
                }
            } catch(err){
                setLoading(false);
                stop = true;
                setLogs(prev => [...prev, JSON.stringify(err)])
            }


    }


    useEffect(() => {
        fetchLogs();
        intervalRef.current  = setInterval(fetchLogs, 5000);  // 每5秒刷新一次


        //在最终状态时停止
        if ((newJobStatus === JOB_STATE.SUCCESS ||  
            newJobStatus === JOB_STATE.ERROR ||
            newJobStatus === JOB_STATE.STOPPED ||
            newJobStatus === JOB_STATE.TERMINATED
        )){
            intervalRef && clearInterval(intervalRef.current );  // 清除定时器
            setStop(true)
        }
            
        return () => {
            intervalRef && clearInterval(intervalRef.current );  // 清除定时器
        };
    }, []);
    const onRefresh = (event) => {
        event.preventDefault();
        fetchLogs();  // 手动刷新时调用fetchLogs
    };

    const fetchStatus  = () => {
        remotePost({"job_id":jobId}, 'get_job_status').then((res) => {
            console.log('status:',res.job_status);
            setNewStatus(res.job_status);
            if (res.job_status !== 'RUNNING'){
                intervalRef && clearInterval(intervalRef.current );  // 清除取log定时器
            }
        }).catch(err => {
            console.log(err);
        })
    }

    useEffect(() => {
        fetchStatus()
        intervalRef2.current  = setInterval(fetchStatus, 5000);  // 每5秒刷新一次
        //在最终状态时停止
        if ((newJobStatus === JOB_STATE.SUCCESS ||  
             newJobStatus === JOB_STATE.ERROR ||
             newJobStatus === JOB_STATE.STOPPED ||
             newJobStatus === JOB_STATE.TERMINATED
        )){
            clearInterval(intervalRef2.current );  // 清除定时器
        }
        return () => {
            clearInterval(intervalRef2.current );  // 清除定时器
        };
    }, []);

    const stateToColor = (status) => {
        switch (status) {
            case JOB_STATE.RUNNING:
                return 'blue';
            case JOB_STATE.SUCCESS:
                return 'green';
            case JOB_STATE.ERROR:
                return 'red';
            case JOB_STATE.STOPPED:
                return 'red';
            case JOB_STATE.TERMINATED:
                return'red';
        }
    }


    return (
        <Container
            header={<Header variant="h2"
            info={<Badge color={stateToColor(newJobStatus)}>{newJobStatus}</Badge>}
            >Training Logs</Header>}
        >
        <FormField
          label={`SageMaker Training Job Name: ${jobRunName}`}
          secondaryControl={<Button data-testid="header-btn-refresh" 
            iconName="refresh" 
            loading={loading}
            disabled={stopRefresh}
            onClick={onRefresh} >Reloading</Button>}
          stretch={true}
        >
            <Textarea  value={logs.join('\n')} readOnly rows={rows}/>
        </FormField>
        </Container>

    )
}
