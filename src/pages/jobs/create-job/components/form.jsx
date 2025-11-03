// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { useState, useEffect, useRef } from 'react';
import { Button, Form, Header, SpaceBetween, Toggle, Flashbar, ExpandableSection, Modal, Box, Alert, Input, FormField } from '@cloudscape-design/components';
import validateField from '../form-validation-config';
import DistributionsPanel from './jobinfo-panel';
import { remotePost } from '../../../../common/api-gateway';
import { useNavigate } from "react-router-dom";
import {LogsPanel} from './log-display';
import {S3Path} from './output-path';
import {useSimpleNotifications} from '../../../commons/use-notifications';
import { t } from 'i18next';

// export const FormContext = React.createContext({});
// export const useFormContext = () => React.useContext(FormContext);

function BaseForm({ content, readOnly,loading, errorText = null, onSubmitClick, header,setReadOnly }) {
  const navigate = useNavigate();
  return (
    <form
      onSubmit={ (event) => {
        event.preventDefault();
        onSubmitClick();
      }}
    >
      <Form
        header={header}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={(event)=>{
            event.preventDefault();
            navigate('/jobs');
          }}>
          {t('cancel')}
          </Button>
          {readOnly&&<Button variant="normal" onClick={(event)=>{
            event.preventDefault();
            setReadOnly(false);
          }}>
          {t('copy_to_new')}
          </Button>}
          {!readOnly&&<Button loading={loading} variant="primary">
            {t('create')}
          </Button>}
        </SpaceBetween>
        
        // <FormActions onCancelClick={onCancelClick} readOnly={readOnly} loading={loading} setReadOnly={setReadOnly}/>
      
      }
        errorText={errorText}
        errorIconAriaLabel="Error"
      >
        {content}
      </Form>
    </form>
  );
}

const defaultErrors = {
  model_name: null,
  prompt_template: null,
  job_type: null,
  job_name: null,
  dataset: null,
  s3DataPath: null,
  datasetInfo: null,
  stage: null,
  instance_num: null,
  instance_type: null,
  booster_option:null,
  s3_checkpoint:null,
  s3_model_path:null
};


const fieldsToValidate = [
  'job_name',
  'job_type',
  'model_name',
  'dataset',
  's3DataPath',
  'prompt_template',
  'training_stage',
  'instance_num',
  'instance_type',
  'datasetInfo',
  // 's3BucketSelectedOption',
];

export const FormWithValidation = ({
  loadHelpPanelContent,
  header,
  loading,
  setLoading,
  setNotificationData,
  data,
  _setData,
  setDisplayNotify,
  readOnly,
  setReadOnly,
}) => {
  const [formErrorText, setFormErrorText] = useState(null);
  const [errors, _setErrors] = useState(defaultErrors);
  const [stopModalVisible, setStopModalVisible] = useState(false);
  const [stopLoading, setStopLoading] = useState(false);
  const [confirmText, setConfirmText] = useState('');

  const setErrors = (updateObj = {}) => _setErrors(prevErrors => ({ ...prevErrors, ...updateObj }));
  const setData = (updateObj = {}) => _setData(prevData => ({ ...prevData, ...updateObj }));
  const navigate = useNavigate();
  const { setNotificationItems } = useSimpleNotifications();

  const refs = {
    job_name: useRef(null),
    job_type: useRef(null),
    dataset: useRef(null),
    model_name: useRef(null),
    quant_type: useRef(null),
    stage: useRef(null),
    // s3BucketSelectedOption: useRef(null),
    instance_type:useRef(null),
    instance_num:useRef(null),
    prompt_template:useRef(null),
    finetuning_method:useRef(null),
    learning_rate:useRef(null),
    per_device_train_batch_size:useRef(null),
    gradient_accumulation_steps:useRef(null),
    num_train_epochs:useRef(null),
    training_precision:useRef(null),
    max_samples:useRef(null),
    cutoff_len:useRef(null),
    val_size:useRef(null),
    s3DataPath:useRef(null),
    datasetInfo:useRef(null),
    booster_option:useRef(null),
    deepspeed:useRef(null),
    s3_checkpoint:useRef(null),
    s3_model_path:useRef(null)
  };
  const onSubmit = () => {
    console.log('data:',data);

    const newErrors = { ...errors };
    let validatePass = true;
    fieldsToValidate.forEach(attribute => {
      const { errorText } = validateField(attribute, data[attribute], data[attribute]);
      newErrors[attribute] = errorText;
      if (errorText) {
        console.log(errorText);
        validatePass = false;
      }
    });
    setErrors(newErrors);
    focusTopMostError(newErrors);
    // console.log(validatePass);
    
    if (validatePass) {
      //submit 
      setLoading(true);
      const formData = {
        job_name: data.job_name,
        job_type: data.stage,
        job_payload:{
          model_name: data.model_name,
          dataset: data.dataset,
          prompt_template: data.prompt_template,
          stage: data.stage,
          quantization_bit: data.quantization_bit,
          finetuning_method:data.finetuning_method,
          learning_rate:data.learning_rate,
          per_device_train_batch_size:data.per_device_train_batch_size,
          gradient_accumulation_steps:data.gradient_accumulation_steps,
          num_train_epochs:data.num_train_epochs,
          training_precision:data.training_precision,
          max_samples:data.max_samples,
          cutoff_len:data.cutoff_len,
          val_size:data.val_size,
          logging_steps:data.logging_steps,
          warmup_steps:data.warmup_steps,
          save_steps:data.save_steps,
          optimizer:data.optimizer,
          lora_rank:data.lora_rank,
          lora_alpha:data.lora_alpha,
          instance_type:data.instance_type,
          instance_num:data.instance_num,
          s3_data_path:data.s3DataPath,
          dataset_info:data.datasetInfo,
          dataset_info2:data.datasetInfo2,
          booster_option:data.booster_option,
          deepspeed:data.deepspeed,
          s3_checkpoint:data.s3_checkpoint,
          s3_model_path:data.s3_model_path,
          use_spot:data.use_spot,
          max_spot_wait:data.max_spot_wait,
          max_job_run_hour:data.max_job_run_hour,
          lora_target_modules:data.lora_target_modules,
          pref_beta:data.pref_beta,
          pref_loss:data.pref_loss,
          pref_ftx:data.pref_ftx,
          max_steps:data.max_steps,
          max_prompt_length:data.max_prompt_length,
          max_response_length:data.max_response_length,
          save_freq:data.save_freq,
          val_freq:data.val_freq,
          limit_images:data.limit_images,
          rollout_tensor_parallel_size:data.rollout_tensor_parallel_size,
          reward_function:data.reward_function,
          customize_reward_function:data.customize_reward_function,
          format_prompt:data.format_prompt,
          format_prompt_type:data.format_prompt_type,
          total_epochs:data.total_epochs,
          global_batch_size:data.global_batch_size,
          rollout_batch_size:data.rollout_batch_size,
          offload_optimizer:data.offload_optimizer,
          offload_params:data.offload_params,
          rollout_num:data.rollout_num,
          val_temperature:data.val_temperature,
          mini_rollout_batch_size:data.mini_rollout_batch_size,
          clip_ratio_high:data.clip_ratio_high,
          clip_ratio_low:data.clip_ratio_low,
          training_plan:data.training_plan,
          



          // lora_r:data.lora_r,
          // lora_dropout:data.lora_dropout,
          // lora_bias:data.lora_bias,
          // lora_module_name:data.lora_module_name,
          // lora_target_modules:data.lora_target_modules,
          // lora_target_modules_type:data.lora_target_modules_type,
        },
    
      };
      const msgid = `msg-${Math.random().toString(8)}`;
      remotePost(formData, 'create_job').
        then(res => {
          // setDisplayNotify(true);
          // setNotificationData({ status: 'success', content: `Create job:${res.response_id}` });
          setNotificationItems((item) => [
            ...item,
            {
              type: "success",
              content:`Create job:${res.response_id}`,
              dismissible: true,
              dismissLabel: "Dismiss message",
              onDismiss: () =>
                setNotificationItems((items) =>
                  items.filter((item) => item.id !== msgid)
                ),
              id: msgid,
            },
          ]);
          setLoading(false);
          navigate('/jobs')
        })
        .catch(err => {
          // setDisplayNotify(true);
          // setNotificationData({ status: 'error', content: `Create job failed` });
          setNotificationItems((item) => [
            ...item,
            {
              type: "error",
              content:`Create job failed`,
              dismissible: true,
              dismissLabel: "Dismiss message",
              onDismiss: () =>
                setNotificationItems((items) =>
                  items.filter((item) => item.id !== msgid)
                ),
              id: msgid,
            },
          ]);
          setLoading(false);
        })
    }
  };

  const shouldFocus = (errorsState, attribute) => {
    let shouldFocus = errorsState[attribute]?.length > 0;

    if (attribute === 'functions' && !shouldFocus) {
      shouldFocus = errorsState.functionFiles?.length > 0;
    }

    return shouldFocus;
  };

  const focusTopMostError = errorsState => {
    for (const [attribute, ref] of Object.entries(refs)) {
      if (shouldFocus(errorsState, attribute)) {
        if (ref.current?.focus) {
          return ref.current.focus();
        }

        if (ref.current?.focusAddButton) {
          return ref.current.focusAddButton();
        }
      }
    }
  };

  const handleStopAndDelete = () => {
    setStopLoading(true);
    const msgid = `msg-${Math.random().toString(8)}`;
    const formData = { job_id: data.job_id };

    remotePost(formData, 'stop_and_delete_job')
      .then(res => {
        setStopLoading(false);
        setStopModalVisible(false);
        setConfirmText(''); // Reset confirmation text

        if (res.response.code === 'SUCCESS') {
          setNotificationItems((item) => [
            ...item,
            {
              type: "success",
              content: res.response.message || `Job ${data.job_id} stopped and deleted successfully`,
              dismissible: true,
              dismissLabel: "Dismiss message",
              onDismiss: () =>
                setNotificationItems((items) =>
                  items.filter((item) => item.id !== msgid)
                ),
              id: msgid,
            },
          ]);
          // Navigate back to jobs list
          navigate('/jobs');
        } else {
          setNotificationItems((item) => [
            ...item,
            {
              type: "error",
              content: res.response.message || `Failed to stop and delete job`,
              dismissible: true,
              dismissLabel: "Dismiss message",
              onDismiss: () =>
                setNotificationItems((items) =>
                  items.filter((item) => item.id !== msgid)
                ),
              id: msgid,
            },
          ]);
        }
      })
      .catch(err => {
        setStopLoading(false);
        setStopModalVisible(false);
        setConfirmText(''); // Reset confirmation text
        setNotificationItems((item) => [
          ...item,
          {
            type: "error",
            content: `Failed to stop and delete job: ${err.message || 'Unknown error'}`,
            dismissible: true,
            dismissLabel: "Dismiss message",
            onDismiss: () =>
              setNotificationItems((items) =>
                items.filter((item) => item.id !== msgid)
              ),
            id: msgid,
          },
        ]);
      });
  };

  // Check if job can be stopped
  const canStopJob = () => {
    const stoppableStatuses = ['SUBMITTED', 'CREATING', 'RUNNING', 'PENDING'];
    return readOnly && data?.job_status && stoppableStatuses.includes(data.job_status);
  };

  return (
    <BaseForm
      header={<Header
        variant="h1"
        actions={readOnly && (
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="normal" onClick={(event)=>{
              event.preventDefault();
              setReadOnly(false);
            }}>
              {t('copy_to_new')}
            </Button>
            {canStopJob() && (
              <Button
                variant="primary"
                onClick={(event) => {
                  event.preventDefault();
                  setStopModalVisible(true);
                }}
              >
                {t('Stop & Delete')}
              </Button>
            )}
          </SpaceBetween>
        )}

      >
        {t('job_detail')}
      </Header>}
      content={
        <SpaceBetween size="l">
          {/* Display error message if job status is ERROR and error_message exists */}
          {readOnly && data?.job_status === 'ERROR' && data?.error_message && (
            <Flashbar
              items={[
                {
                  type: "error",
                  dismissible: false,
                  header: "Job Execution Failed",
                  content: (
                    <ExpandableSection
                      headerText="View detailed error information"
                      variant="footer"
                    >
                      <pre style={{
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word',
                        // backgroundColor: '#fff',
                        padding: '12px',
                        borderRadius: '4px',
                        // border: '1px solid #d5dbdb',
                        maxHeight: '400px',
                        overflow: 'auto',
                        fontSize: '12px',
                        fontFamily: 'Monaco, Menlo, "Courier New", monospace',
                        margin: 0
                      }}>
                        {data.error_message}
                      </pre>

                      {/* {data.error_message} */}
                    </ExpandableSection>
                  ),
                  id: "error-message"
                }
              ]}
            />
          )}

          {/* Stop & Delete confirmation modal */}
          <Modal
            onDismiss={() => {
              setStopModalVisible(false);
              setConfirmText('');
            }}
            visible={stopModalVisible}
            footer={
              <Box float="right">
                <SpaceBetween direction="horizontal" size="xs">
                  <Button
                    variant="link"
                    onClick={() => {
                      setStopModalVisible(false);
                      setConfirmText('');
                    }}
                  >
                    {t('cancel')}
                  </Button>
                  <Button
                    variant="primary"
                    onClick={handleStopAndDelete}
                    loading={stopLoading}
                    disabled={confirmText !== 'confirm'}
                  >
                    {t('Confirm')}
                  </Button>
                </SpaceBetween>
              </Box>
            }
            header={t('Stop and Delete Job')}
          >
            <SpaceBetween size="m">
              <Alert type="warning">
                <strong>{t('Warning:')}</strong> {t('停止后无法恢复')} {t('This action cannot be undone.')}
              </Alert>

              <Box>
                <Box variant="p">
                  {t('Are you sure you want to stop and delete this job?')}
                </Box>
              </Box>

              <Box>
                <strong>{t('Job ID:')}</strong> {data?.job_id}
              </Box>
              <Box>
                <strong>{t('Job Name:')}</strong> {data?.job_name}
              </Box>
              <Box>
                <strong>{t('Current Status:')}</strong> {data?.job_status}
              </Box>

              <FormField
                label={t('Type "confirm" to proceed')}
                description={t('Please type the word "confirm" to enable the deletion button.')}
              >
                <Input
                  value={confirmText}
                  onChange={({ detail }) => setConfirmText(detail.value)}
                  placeholder="confirm"
                  autoFocus
                />
              </FormField>
            </SpaceBetween>
          </Modal>

          <DistributionsPanel
            loadHelpPanelContent={loadHelpPanelContent}
            validation={true}
            data={data}
            errors={errors}
            setData={setData}
            setErrors={setErrors}
            refs={refs}
            readOnly={readOnly}
          />
          {readOnly&&<S3Path outputPath={data?.output_s3_path} label={"Model Output S3 Path"}/>}
          {readOnly&&<LogsPanel jobRunName={data?.job_run_name} jobStatus={data?.job_status} jobId={data?.job_id}/>}
        </SpaceBetween>
      }
      loading={loading}
      onSubmitClick={onSubmit}
      setReadOnly={setReadOnly}
      readOnly={readOnly}
      errorText={formErrorText}
    />
  );
};
