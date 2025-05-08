// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { useRef, useState } from 'react';
// import { createRoot } from 'react-dom/client';
import { CustomAppLayout, Navigation, Notifications } from '../../commons/common-components';
import { Breadcrumbs, createjobBreadcrumbs } from '../../commons/breadcrumbs'
import {FORMAT_PROMPT_OPTIONS} from './form-config';
import { FormWithValidation } from './components/form';
// import ToolsContent from './components/tools-content';
import '../../../styles/form.scss';

const datasetInfoExample = `{"your_dataset_key1":
    {
        "file_name":"your_dataset_name.json",
        "columns": {
            "prompt": "instruction",
            "query": "input",
            "response": "output"
        }
    },
    "your_dataset_key2":
    {
        "file_name":"your_dataset_name_2.json"
    }
}`

const datasetInfoExample2 = `{
    "train_file":"your_dataset_name.parquet",
    "val_file":"your_dataset_name.parquet"
}`

const defaultDataLF = {
  model_name: null,
  prompt_template: null,
  job_type: 'lora',
  job_name: '',
  quantization_bit: 'none',
  finetuning_method: 'lora',
  stage: 'Supervised Fine-Tuning',
  learning_rate: '5e-5',
  per_device_train_batch_size: 2,
  gradient_accumulation_steps: 4,
  num_train_epochs: 2.0,
  training_precision: 'bf16',
  max_samples: 50000,
  cutoff_len: 1024,
  val_size: 0.05,
  logging_steps: 10,
  warmup_steps: 10,
  save_steps: 500,
  optimizer: 'adamw_torch',
  lora_rank: 8,
  lora_alpha: 16,
  instance_type: null,
  instance_num: 1,
  datasetInfo: datasetInfoExample,
  booster_option: 'auto',
  deepspeed: 'none',
  s3_checkpoint:'',
  s3_model_path:'',
  use_spot: false,
  max_spot_wait:72,
  max_job_run_hour:72,
  lora_target_modules:'all',
  pref_loss:'sigmoid',
  pref_beta:0.1,
  pref_ftx:0
};

//For easyr1
const defaultDataEasyR1 = {
  max_steps:10000,
  total_epochs:10,
  max_prompt_length: 2048,
  max_response_length: 2048,
  save_freq: 50,
  val_freq:50,
  limit_images:0,
  rollout_tensor_parallel_size:1,
  datasetInfo2: datasetInfoExample2,
  reward_function:'math:compute_score',
  customize_reward_function:'',
  format_prompt:FORMAT_PROMPT_OPTIONS['math'],
  format_prompt_type:'math',
  rollout_batch_size:512,
  global_batch_size:128,
  offload_optimizer:false,
  offload_params:false,
  rollout_num:5,
  val_temperature:0.1
}

const defaultData = {...defaultDataLF,...defaultDataEasyR1};



const CreateJobApp = () => {
  const [toolsIndex, setToolsIndex] = useState(0);
  const [toolsOpen, setToolsOpen] = useState(false);
  const appLayout = useRef();
  const [notificationData, setNotificationData] = useState({});
  const [displayNotify, setDisplayNotify] = useState(false);
  const [data, _setData] = useState(defaultData);
  const [loading, setLoading] = useState(false);

  const loadHelpPanelContent = index => {
    setToolsIndex(index);
    setToolsOpen(true);
    appLayout.current?.focusToolsClose();
  };

  return (
    <CustomAppLayout
      ref={appLayout}
      contentType="form"
      content={
        <FormWithValidation
          loadHelpPanelContent={loadHelpPanelContent}
          loading={loading}
          setLoading={setLoading}
          data={data}
          _setData={_setData}
          setNotificationData={setNotificationData}
          setDisplayNotify={setDisplayNotify}
        />
      }
      breadcrumbs={<Breadcrumbs items={createjobBreadcrumbs} />}
      navigation={<Navigation activeHref="#/jobs" />}
      // tools={ToolsContent[toolsIndex]}
      toolsOpen={toolsOpen}
      onToolsChange={({ detail }) => setToolsOpen(detail.open)}
      notifications={<Notifications
        successNotification={displayNotify}
        data={notificationData} />}
    />
  );
}


export default CreateJobApp;
// createRoot(document.getElementById('app')).render(<App />);
