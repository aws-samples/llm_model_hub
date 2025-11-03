// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { useEffect, useState,useCallback,useRef } from 'react';
import { remotePost } from '../../../../common/api-gateway';
import Textarea from "@cloudscape-design/components/textarea";
import FormField from "@cloudscape-design/components/form-field";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Container  from '@cloudscape-design/components/container';
import Header from "@cloudscape-design/components/header";
import Badge from "@cloudscape-design/components/badge";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Toggle from "@cloudscape-design/components/toggle";
import {JOB_STATE} from "../../table-config";
import { AnsiLog } from './ansi-log';
const defaultRows = 20;
const defaultMaxRows = 50;
const MAX_LOG_LINES = 5000; // Maximum number of log lines to keep in memory
export const LogsPanel = ({jobRunName,jobId,jobStatus}) => {
    const [logs, setLogs] = useState(['Start running, please wait a few minutes...']);
    const [loading, setLoading] = useState(false);
    const [rows, setRows] = useState(defaultRows);
    const [stopRefresh,setStop] = useState(false);
    const [newJobStatus, setNewStatus] = useState(jobStatus);
    const [totalLogLines, setTotalLogLines] = useState(0);
    const [isAutoScroll, setIsAutoScroll] = useState(true);
    const [enableAnsi, setEnableAnsi] = useState(true); // Enable ANSI rendering by default
    const intervalRef = useRef(null);
    const intervalRef2 = useRef(null);
    const nextTokenRef = useRef(null);
    const textareaRef = useRef(null);
    const logContainerRef = useRef(null);
    const allLogsRef = useRef([]); // Store all logs for download

    function sortEventsByTimestamp(events) {
        return events.sort((a, b) => {
            // 从每个字符串中提取时间戳
            const timestampA = new Date(a.split(': ')[0]);
            const timestampB = new Date(b.split(': ')[0]);

            // 比较时间戳
            return timestampA - timestampB;
        });
    }

    // Optimized fetchLogs: removed while loop, single request per call
    const fetchLogs = async () => {
        setLoading(true);
        let params = {
            "next_token": nextTokenRef.current,
            'job_id':jobId
        };

        try {
            const res = await remotePost(params, 'fetch_training_log');
            setLoading(false);
            console.log('logs:', res.next_forward_token);

            // Check if there are new logs
            if (res.next_forward_token !== params.next_token) {
                nextTokenRef.current = res.next_forward_token;

                if (res.log_events && res.log_events.length > 0) {
                    const sortedEvents = sortEventsByTimestamp(res.log_events);

                    // Store all logs for download
                    allLogsRef.current = [...allLogsRef.current, ...sortedEvents];
                    setTotalLogLines(allLogsRef.current.length);

                    // Keep only the latest MAX_LOG_LINES in display
                    setLogs((prev) => {
                        const newLogs = [...prev, ...sortedEvents];
                        if (newLogs.length > MAX_LOG_LINES) {
                            // Keep only the most recent MAX_LOG_LINES
                            return newLogs.slice(-MAX_LOG_LINES);
                        }
                        return newLogs;
                    });

                    // Update rows based on log length
                    setRows((prevRows) => {
                        const newLength = Math.min(logs.length + sortedEvents.length, MAX_LOG_LINES);
                        if (newLength > defaultRows) {
                            return newLength > defaultMaxRows ? defaultMaxRows : newLength;
                        }
                        return defaultRows;
                    });

                    // Auto-scroll to bottom if enabled
                    if (isAutoScroll) {
                        setTimeout(() => {
                            // For textarea
                            if (textareaRef.current) {
                                textareaRef.current.scrollTop = textareaRef.current.scrollHeight;
                            }
                            // For ANSI log container
                            if (logContainerRef.current) {
                                logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
                            }
                        }, 100);
                    }
                }
            }
        } catch(err){
            setLoading(false);
            console.error('Error fetching logs:', err);
            setLogs(prev => [...prev, `Error: ${err.message || JSON.stringify(err)}`]);
        }
    }


    // Download logs functionality
    const downloadLogs = () => {
        const logContent = allLogsRef.current.join('\n');
        const blob = new Blob([logContent], { type: 'text/plain' });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${jobRunName || jobId}_logs_${new Date().toISOString().split('T')[0]}.txt`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
    };

    // Clear logs functionality
    const clearLogs = () => {
        setLogs(['Logs cleared. New logs will appear here...']);
        // Don't clear allLogsRef to keep full history for download
    };

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
            >Training Logs {totalLogLines > 0 && `(${totalLogLines} total lines, showing last ${Math.min(logs.length, MAX_LOG_LINES)})`}</Header>}
        >
        <FormField
          label={`SageMaker Training Job Name: ${jobRunName}`}
          secondaryControl={
            <SpaceBetween direction="horizontal" size="xs">
              <Toggle
                checked={enableAnsi}
                onChange={({ detail }) => setEnableAnsi(detail.checked)}
              >
                ANSI Colors
              </Toggle>
              <Button
                iconName={isAutoScroll ? "check" : "close"}
                variant={isAutoScroll ? "primary" : "normal"}
                onClick={() => setIsAutoScroll(!isAutoScroll)}
              >
                Auto-scroll
              </Button>
              <ButtonDropdown
                items={[
                  { id: "download", text: "Download all logs", iconName: "download" },
                  { id: "clear", text: "Clear display", iconName: "remove" }
                ]}
                onItemClick={({ detail }) => {
                  if (detail.id === "download") {
                    downloadLogs();
                  } else if (detail.id === "clear") {
                    clearLogs();
                  }
                }}
              >
                Actions
              </ButtonDropdown>
              <Button
                data-testid="header-btn-refresh"
                iconName="refresh"
                loading={loading}
                disabled={stopRefresh}
                onClick={onRefresh}
              >
                Refresh
              </Button>
            </SpaceBetween>
          }
          stretch={true}
        >
            {enableAnsi ? (
              <div
                ref={logContainerRef}
                style={{
                  maxHeight: `${rows * 20}px`,
                  overflowY: 'auto',
                  border: '1px solid #21262d',
                  borderRadius: '4px',
                  backgroundColor: '#0f1419'
                }}
              >
                {logs.map((log, index) => (
                  <AnsiLog key={index} debug={index === 0}>{log}</AnsiLog>
                ))}
              </div>
            ) : (
              <Textarea
                ref={textareaRef}
                value={logs.join('\n')}
                readOnly
                rows={rows}
              />
            )}
        </FormField>
        </Container>

    )
}
