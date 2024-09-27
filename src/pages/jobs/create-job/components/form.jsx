// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { useState, useEffect, useRef } from 'react';
import { Button, Form, Header, SpaceBetween, Toggle } from '@cloudscape-design/components';
import validateField from '../form-validation-config';
import DistributionsPanel from './jobinfo-panel';
import { remotePost } from '../../../../common/api-gateway';
import { useNavigate } from "react-router-dom";
import {LogsPanel} from './log-display';
import {S3Path} from './output-path';
import {useSimpleNotifications} from '../../../commons/use-notifications';

// export const FormContext = React.createContext({});
// export const useFormContext = () => React.useContext(FormContext);

export function FormHeader({ readOnly,loadHelpPanelContent }) {
  return (
    <Header
      variant="h1"
    >
      Job Detail
    </Header>
  );
}

function FormActions({ onCancelClick ,loading,readOnly}) {
  return (
    <SpaceBetween direction="horizontal" size="xs">
      <Button variant="link" onClick={onCancelClick}>
        Cancel
      </Button>
      {!readOnly&&<Button loading={loading} data-testid="create" variant="primary">
        Create
      </Button>}
    </SpaceBetween>
  );
}

function BaseForm({ content, readOnly,onCancelClick,loading, errorText = null, onSubmitClick, header }) {
  return (
    <form
      onSubmit={event => {
        event.preventDefault();
        if (onSubmitClick) {
          onSubmitClick();
        }
      }}
    >
      <Form
        header={header}
        actions={<FormActions onCancelClick={onCancelClick} readOnly={readOnly} loading={loading}/>}
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
  readOnly
}) => {
  const [formErrorText, setFormErrorText] = useState(null);
  const [errors, _setErrors] = useState(defaultErrors);

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
  const onCancelClick =()=>
  {
    navigate('/jobs')
  }
  const onSubmit = () => {
    console.log(data);

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
          booster_option:data.booster_option,
          deepspeed:data.deepspeed,
          s3_checkpoint:data.s3_checkpoint,
          s3_model_path:data.s3_model_path,
          use_spot:data.use_spot,
          max_spot_wait:data.max_spot_wait,
          max_job_run_hour:data.max_job_run_hour
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

  return (
    <BaseForm
      header={header}
      content={
        <SpaceBetween size="l">
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
      readOnly={readOnly}
      onCancelClick={onCancelClick}
      errorText={formErrorText}
    />
  );
};
