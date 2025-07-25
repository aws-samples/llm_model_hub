// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { useEffect, useState } from 'react';
import {
  Container,
  Checkbox,
  ExpandableSection,
  Header,
  Input,
  RadioGroup,
  FormField,
  SpaceBetween,
  Select,
  Grid,
  Link,
  Multiselect,
  Toggle,
  Textarea,
} from '@cloudscape-design/components';
import { FT_OPTIONS, QUANT_OPTIONS, TRAINING_STAGES, TRAINING_PRECISION, OPTMIZERS, INSTANCE_TYPES, BOOSTER_OPTIONS, DEEPSPEED,FORMAT_PROMPT_OPTIONS } from '../form-config';
import validateField from '../form-validation-config';
import { remotePost } from '../../../../common/api-gateway';
import { S3Selector } from './output-path';
import { JsonEditor,PythonEditor } from './code-editor';
import { t } from 'i18next';


function AdvancedConfigs({ onChange, readOnly, data, setData }) {
  return (
    <SpaceBetween size="l">
      <ExpandableSection headerText={`Extra ${t('configurations')}`} variant="footer">
        <Grid
          gridDefinition={[{ colspan: { default: 6, xxs: 4 } }, { colspan: { default: 6, xxs: 4 } }]}
        >
          <FormField
            label="Warmup steps"
            description="Number of steps used for warmup."
            stretch={false}
          >
            <Input readOnly={readOnly}
              value={readOnly ? data.job_payload?.warmup_steps : data.warmup_steps}
              onChange={({ detail: { value } }) => onChange('warmup_steps', value)}
            />
          </FormField>
          <FormField
            label="Logging steps"
            description="Number of steps between two logs."
            stretch={false}
          >
            <Input readOnly={readOnly}
              value={readOnly ? data.job_payload?.logging_steps : data.logging_steps}
              onChange={({ detail: { value } }) => onChange('logging_steps', value)}
            />
          </FormField>
        </Grid>
        <Grid
          gridDefinition={[{ colspan: { default: 6, xxs: 4 } }, { colspan: { default: 6, xxs: 4 } }]}
        >
          <FormField
            label="Save steps"
            description="Number of steps between two checkpoints."
            stretch={false}
          >
            <Input readOnly={readOnly}
              value={readOnly ? data.job_payload?.save_steps : data.save_steps}
              onChange={({ detail: { value } }) => onChange('save_steps', value)}
            />
          </FormField>
          <FormField
            label="Optimizer"
            description="The optimizer to use."
            stretch={false}
          >
            <SelectOptimizer readOnly={readOnly} data={data} setData={setData} />
          </FormField>
        </Grid>

      </ExpandableSection>
      <ExpandableSection headerText={`Lora ${t('configurations')}`} variant="footer">
        <Grid
          gridDefinition={[{ colspan: { default: 6, xxs: 4 } }, { colspan: { default: 6, xxs: 4 } }]}
        >
          <FormField
            label="LoRA rank"
            description="The rank of LoRA matrices."
            stretch={false}
          >
            <Input readOnly={readOnly}
              value={readOnly ? data.job_payload?.lora_rank : data.lora_rank}
              onChange={({ detail: { value } }) => onChange('lora_rank', value)}
            />
          </FormField>
          <FormField
            label="LoRA alpha"
            description="Lora scaling coefficient."
            stretch={false}
          >
            <Input readOnly={readOnly}
              value={readOnly ? data.job_payload?.lora_alpha : data.lora_alpha}
              onChange={({ detail: { value } }) => onChange('lora_alpha', value)}
            />
          </FormField>
        </Grid>
        <Grid
          gridDefinition={[{ colspan: { default: 6, xxs: 4 } }, { colspan: { default: 6, xxs: 4 } }]}
        >
          <FormField
            label="LoRA Target Modules"
            description="Lora target modules such as v_proj,k_proj, default is all, which apply to all linear layers"
            stretch={false}
          >
            <Input readOnly={readOnly}
              value={readOnly ? data.job_payload?.lora_target_modules : data.lora_target_modules}
              onChange={({ detail: { value } }) => onChange('lora_target_modules', value)}
            />
          </FormField>
        </Grid>
      </ExpandableSection>
      <ExpandableSection headerText={`RLHF ${t('configurations')}`} variant="footer">
        <Grid
          gridDefinition={[{ colspan: { default: 6, xxs: 4 } }, { colspan: { default: 6, xxs: 4 } }]}
        >
          <FormField
            label={t("rlhf_beta")}
            description={t("rlhf_beta_desc")}
            stretch={false}
          >
            <Input readOnly={readOnly}
              value={readOnly ? data.job_payload?.pref_beta : data.pref_beta}
              onChange={({ detail: { value } }) => onChange('pref_beta', value)}
            />
          </FormField>
          <FormField
            label={t("rlhf_ftx_gamma")}
            description={t("rlhf_ftx_gamma_desc")}
            stretch={false}
          >
            <Input readOnly={readOnly}
              value={readOnly ? data.job_payload?.pref_ftx : data.pref_ftx}
              onChange={({ detail: { value } }) => onChange('pref_ftx', value)}
            />
          </FormField>
        </Grid>
        <Grid
          gridDefinition={[{ colspan: { default: 6, xxs: 4 } }, { colspan: { default: 6, xxs: 4 } }]}
        >
          <FormField
            label={t("rlhf_loss_type")}
            stretch={false}
          >
            <SelectLossType data={data} setData={setData} readOnly={readOnly} />
          </FormField>
        </Grid>
      </ExpandableSection>
    </SpaceBetween>
  );
}

function DeepSpeedConfigs({ onChange, readOnly, data, setData }) {
  return (
    <SpaceBetween size="l">
      <ExpandableSection headerText="DeepSpeed configurations (Applicable for Multi-GPU/Nodes)" variant="footer" expanded>
        <Grid
          gridDefinition={[{ colspan: { default: 6, xxs: 4 } }, { colspan: { default: 6, xxs: 4 } }]}
        >
          <FormField
            label="DeepSpeed Stage"
            description="DeepSpeed stage for distributed training."
            stretch={false}
          >
            <RadioGroup
              items={DEEPSPEED}
              value={readOnly ? data.job_payload?.deepspeed : data.deepspeed}
              onChange={({ detail: { value } }) => onChange('deepspeed', value)}
              readOnly={readOnly}
            />
          </FormField>
        </Grid>
      </ExpandableSection>

    </SpaceBetween>
  );
}

const SelectPromptTemplate = ({ data, setData, readOnly, refs }) => {
  const [loadStatus, setLoadStatus] = useState("loading");
  const [items, setItems] = useState([]);
  // const initState = data.job_payload ? { label: data.job_payload.prompt_template, value: data.job_payload.prompt_template } : {};
  const [selectOption, setSelectOption] = useState({});
  useEffect(() => {
    if (data.job_payload) {
      setSelectOption({ label: data.job_payload.prompt_template, value: data.job_payload.prompt_template });
      setData({ prompt_template: data.job_payload.prompt_template })
    }
  }, [data.job_payload]);
  const handleLoadItems = async ({
    detail: { filteringText, firstPage, samePage },
  }) => {
    setLoadStatus("loading");
    try {
      const data = await remotePost({ config_name: 'prompt_template' }, 'get_factory_config');
      const items = data.response.body.map((it) => ({
        prompt_template: it,
      }));
      setItems(items);
      setLoadStatus("finished");
    } catch (error) {
      console.log(error);
      setLoadStatus("error");
    }
  };
  return (
    <Select
      statusType={loadStatus}
      onLoadItems={handleLoadItems}
      selectedOption={selectOption}
      disabled={readOnly}
      onChange={({ detail }) => {
        setSelectOption(detail.selectedOption);
        setData({ prompt_template: detail.selectedOption.value })
      }}
      options={items.map(({ prompt_template }) => ({
        label: prompt_template,
        value: prompt_template,
      }))}
      selectedAriaLabel="Selected"
      ref={refs.prompt_template}
    />
  )
}


const SelectModelName = ({ data, setData, readOnly, refs }) => {
  const [loadStatus, setLoadStatus] = useState("loading");
  const [items, setItems] = useState([]);
  const [selectOption, setSelectOption] = useState({});
  useEffect(() => {
    if (data.job_payload) {
      setSelectOption({ label: data.job_payload.model_name, value: data.job_payload.model_name })
      setData({ model_name: data.job_payload.model_name })
    }
  }, [data.job_payload])
  const handleLoadItems = async ({
    detail: { filteringText, firstPage, samePage },
  }) => {
    setLoadStatus("loading");
    try {
      const data = await remotePost({ config_name: 'model_name' }, 'get_factory_config');
      const items = data.response.body.map((it) => ({
        model_name: it.model_name,
        model_path: it.model_path,
      }));
      setItems(items);
      setLoadStatus("finished");
    } catch (error) {
      console.log(error);
      setLoadStatus("error");
    }
  };
  return (
    <Select
      statusType={loadStatus}
      onLoadItems={handleLoadItems}
      disabled={readOnly}
      selectedOption={selectOption}
      onChange={({ detail }) => {
        setSelectOption(detail.selectedOption);
        setData({ model_name: detail.selectedOption.value })
      }}
      options={items.map(({ model_name, model_path }) => ({
        label: model_name,
        value: model_path,
        tags: [model_path]
      }))}
      selectedAriaLabel="Selected"
      ref={refs.model_name}
    />
  )
}

const SelectDatasets = ({ data, setData, readOnly, refs }) => {
  const [loadStatus, setLoadStatus] = useState("loading");
  const [items, setItems] = useState([]);

  const initState = data.job_payload && data.job_payload.dataset ? data.job_payload.dataset.map(item => ({
    label: item, value: item
  })) : []
  // const [selectOption, setSelectOption] = useState(initState);

  const [selectedOptions, setSelectOptions] = useState(initState);
  const handleLoadItems = async ({
    detail: { filteringText, firstPage, samePage },
  }) => {
    setLoadStatus("loading");
    try {
      const resp = await remotePost({ config_name: 'dataset', stage: data.stage }, 'get_factory_config');
      const items = resp.response.body.map((it) => ({
        dataset: it,
      }));
      setItems(items);
      setLoadStatus("finished");
    } catch (error) {
      console.log(error);
      setLoadStatus("error");
    }
  };
  useEffect(() => {
    setSelectOptions(initState);
    setLoadStatus("pending");
    setItems([]);
  }, [data.stage])

  return (
    <Multiselect
      statusType={loadStatus}
      onLoadItems={handleLoadItems}
      disabled={readOnly}
      selectedOptions={selectedOptions}
      onChange={({ detail }) => {
        setSelectOptions(detail.selectedOptions);
        setData({ dataset: detail.selectedOptions.map(it => it.value) })
      }}
      options={items.map(({ dataset }) => ({
        label: dataset,
        value: dataset,
      }))}
      selectedAriaLabel="Selected"
      ref={refs.dataset}
    />
  )
}

const SelectStage = ({ data, setData, readOnly, refs }) => {

  const initState = TRAINING_STAGES.filter(item => data.job_payload?.stage === item.value)
  const [selectOption, setSelectOption] = useState(initState.length ? initState[0] : {});
  return (
    <Select
      selectedOption={selectOption}
      disabled={readOnly}
      onChange={({ detail }) => {
        setSelectOption(detail.selectedOption);
        setData({ stage: detail.selectedOption.value })
      }}
      options={TRAINING_STAGES}
      selectedAriaLabel="Selected"
      ref={refs.stage}
    />
  )
}

const SelectOptimizer = ({ data, setData, readOnly, refs }) => {
  const initState = OPTMIZERS.filter(item => data.job_payload?.optimizer === item.value)
  const [selectOption, setSelectOption] = useState(initState.length ? initState[0] : OPTMIZERS[0]);
  return (
    <Select
      selectedOption={selectOption}
      disabled={readOnly}
      onChange={({ detail }) => {
        setSelectOption(detail.selectedOption);
        setData({ optimizer: detail.selectedOption.value })
      }}
      options={OPTMIZERS}
      selectedAriaLabel="Selected"
    />
  )
}

const SelectInstanceType = ({ data, setData, readOnly, refs }) => {
  // const initState = INSTANCE_TYPES.filter(item => data.job_payload?.instance_type === item.value)
  const [selectOption, setSelectOption] = useState([]);
  useEffect(() => {
    if (data.job_payload) {
      setSelectOption({ label: data.job_payload.instance_type, value: data.job_payload.instance_type })
      setData({ instance_type: data.job_payload.instance_type })
    }
  }, [data.job_payload])
  return (
    <Select
      selectedOption={selectOption}
      disabled={readOnly}
      onChange={({ detail }) => {
        setSelectOption(detail.selectedOption);
        setData({ instance_type: detail.selectedOption.value })
      }}
      options={INSTANCE_TYPES}
      selectedAriaLabel="Selected"
      ref={refs.instance_type}
    />
  )
}

const SelectLossType = ({ data, setData, readOnly }) => {
  // const initState = INSTANCE_TYPES.filter(item => data.job_payload?.instance_type === item.value)
  const [selectOption, setSelectOption] = useState({ label: 'sigmoid', value: 'sigmoid' });
  useEffect(() => {
    if (data.job_payload) {
      setSelectOption({ label: data.job_payload.pref_loss, value: data.job_payload.pref_loss })
      setData({ pref_loss: data.job_payload.pref_loss })
    }
  }, [data.job_payload])
  return (
    <Select
      selectedOption={selectOption}
      disabled={readOnly}
      onChange={({ detail }) => {
        setSelectOption(detail.selectedOption);
        setData({ pref_loss: detail.selectedOption.value })
      }}
      options={[
        { label: 'sigmoid', value: 'sigmoid' },
      ]}
      selectedAriaLabel="Selected"
    />
  )
}

const SelectTrainingPrecision = ({ data, setData, readOnly, refs }) => {

  const initState = TRAINING_PRECISION.filter(item => data.job_payload?.training_precision === item.value)
  const [selectOption, setSelectOption] = useState(initState.length ? initState[0] : TRAINING_PRECISION[0]);
  return (
    <Select
      selectedOption={selectOption}
      disabled={readOnly}
      onChange={({ detail }) => {
        setSelectOption(detail.selectedOption);
        setData({ training_precision: detail.selectedOption.value })
      }}
      options={TRAINING_PRECISION}
      selectedAriaLabel="Selected"
    />
  )
}

const SelectFormatPromptType= ({ data, setData, readOnly, refs }) => {
  const [selectOption, setSelectOption] = useState({ label: 'math', value: 'math' });
  // const [promptContent, setPromptContent] = useState(FORMAT_PROMPT_OPTIONS['math'] );
  useEffect(() => {
    if (data.job_payload) {
      setSelectOption({ label: data.job_payload.format_prompt_type, value: data.job_payload.format_prompt_type });
      setData({ format_prompt_type: data.job_payload.format_prompt_type });
      
    }
  }, [data.job_payload])
  return (
    <SpaceBetween size="l">
    <Select
      selectedOption={selectOption}
      disabled={readOnly}
      onChange={({ detail }) => {
        setSelectOption(detail.selectedOption);
        setData({ format_prompt_type: detail.selectedOption.value });
        if (detail.selectedOption.value !== 'customize'){
          setData({ format_prompt: FORMAT_PROMPT_OPTIONS[detail.selectedOption.value] });
        }else{
          setData({ format_prompt: data.format_prompt});
        }
      }}
      options={[
        { label: 'math', value: 'math' },
        { label: 'r1v', value: 'r1v' },
        { label: 'customize', value: 'customize' }
      ]}
      selectedAriaLabel="Selected"
    />

    <Textarea 
      readOnly={readOnly}
      rows = {5}
      value={readOnly ? data.job_payload?.format_prompt : data.format_prompt}
      onChange={(event) => {
        setData({format_prompt:event.detail.value});
        // setPromptContent(event.detail.value);
      }}
      />
 </SpaceBetween>
  )
}


const SelectRewardFunction = ({ data, setData, readOnly, refs }) => {
  const [selectOption, setSelectOption] = useState({ label: 'math:compute_score', value: 'math:compute_score' });
  useEffect(() => {
    if (data.job_payload) {
      setSelectOption({ label: data.job_payload.reward_function, value: data.job_payload.reward_function })
      setData({ reward_function: data.job_payload.reward_function })
    }
  }, [data.job_payload])
  return (
    <Select
      selectedOption={selectOption}
      disabled={readOnly}
      onChange={({ detail }) => {
        setSelectOption(detail.selectedOption);
        setData({ reward_function: detail.selectedOption.value })
      }}
      options={[
        { label: 'math:compute_score', value: 'math:compute_score' },
        { label: 'r1v:compute_score', value: 'r1v:compute_score' },
        { label: 'customize', value: 'customize' }
      ]}
      selectedAriaLabel="Selected"
    />
  )
}

const EasyR1JobSetting = ({ validation,
  onChange,
  readOnly,
  data,
  errors,
  setData,
  setErrors,
  refs }) =>{

    //bypass the prompt_template
    useEffect(()=>{
      setData({prompt_template:'dummy'});
    },[]);
    return (<SpaceBetween size="xl" direction="vertical">
            <Container
              header={<Header variant="h2">{t('training_job_settings')}</Header>}
            >
              <SpaceBetween size="l">
                <FormField
                  label={t('model_name')}
                  stretch={false}
                  description="Select Model"
                  errorText={errors.model_name}
                  i18nStrings={{ errorIconAriaLabel: 'Error' }}
                >
                  <SelectModelName data={data} setData={setData} readOnly={readOnly} refs={refs} />
                </FormField>
                <FormField
                  label="Use Existing Model Weight (Optional)"
                  stretch={false}
                  description="使用已有的模型文件进行训练"
                  errorText={errors.s3_model_path}
                  i18nStrings={{ errorIconAriaLabel: 'Error' }}
                >
                  <S3Selector
                    readOnly={readOnly}
                    objectsIsItemDisabled={(item) => !item.IsFolder}
                    setOutputPath={(value) => setData({ s3_model_path: value })}
                    outputPath={readOnly ? data.job_payload?.s3_model_path : data.s3_model_path} />
                </FormField>
                <FormField
                  label="Use Existing Checkpoint (Optional)"
                  stretch={false}
                  description="使用已有的checkpoint文件继续训练"
                  errorText={errors.s3_checkpoint}
                  i18nStrings={{ errorIconAriaLabel: 'Error' }}
                >
                  <S3Selector
                    readOnly={readOnly}
                    objectsIsItemDisabled={(item) => !item.IsFolder}
                    setOutputPath={(value) => setData({ s3_checkpoint: value })}
                    outputPath={readOnly ? data.job_payload?.s3_checkpoint : data.s3_checkpoint} />
                </FormField>
                <FormField
                  label={t('finetuning_method')}
                  description="Choose Finetuning method for the job (For GRPO Only support full currently)"
                  stretch={true}
                >
                  <RadioGroup
                    items={FT_OPTIONS}
                    readOnly={readOnly}
                    value={readOnly ? data.job_payload?.finetuning_method : data.finetuning_method}
                    onChange={({ detail: { value } }) => onChange('finetuning_method', value)}
                    ref={refs.finetuning_method}
                  />
                </FormField>
                <FormField
                  label={t("max_job_run_hour")}
                  description={t("max_job_run_hour_desc")}
                  stretch={false}
                >
                  <Input readOnly={readOnly}
                    value={readOnly ? data.job_payload?.max_job_run_hour : data.max_job_run_hour}
                    onChange={({ detail: { value } }) => onChange('max_job_run_hour', value)}
                  />
                </FormField>
              </SpaceBetween>
            </Container>
            <Container
              header={<Header variant="h2">{t('datasets_settings')}</Header>}
            >
              <SpaceBetween size="l">
                <FormField
                  label="Training Data in S3"
                  stretch={false}
                  description="Input the S3 path of your own dataset"
                  errorText={errors.s3DataPath}
                  i18nStrings={{ errorIconAriaLabel: 'Error' }}
                >
                <S3Selector label={"S3 Data Path"}
                  readOnly={readOnly}
                  objectsIsItemDisabled={(item) => !item.IsFolder}
                  setOutputPath={(value) => setData({ s3DataPath: value })}
                  outputPath={readOnly ? data.job_payload?.s3_data_path : data.s3DataPath} />
                </FormField>
                  {(data.job_payload?.s3_data_path || data.s3DataPath) &&
                  <FormField
                    label="Dataset Info"
                    description="Need to prepare a data set info in parquet format. For example"
                    stretch={false}
                  >
                  <JsonEditor
                    readOnly={readOnly}
                    value={readOnly ? data.job_payload?.dataset_info2 : data.datasetInfo2}
                    onDelayedChange={(event) => onChange('datasetInfo2', event.detail.value)}
                  />
                </FormField>}
                <FormField
                  label={t("public_datasets")}
                  stretch={false}
                  description="select open-source datasets from hf"
                  errorText={errors.dataset}
                  i18nStrings={{ errorIconAriaLabel: 'Error' }}
                >
                  <SelectDatasets data={data} setData={setData} readOnly={readOnly} refs={refs} />
                </FormField>
                <Grid gridDefinition={[{ colspan: { "default": 4, xxs: 4 } }, { colspan: { "default": 4, xxs: 4 } },
                ]}>
                  <FormField
                    label={t("max_prompt_length")}
                    description="Maximum Prompt Length."
                    stretch={false}
                  >
                    <Input readOnly={readOnly}
                      value={readOnly ? data.job_payload?.max_prompt_length : data.max_prompt_length}
                      onChange={({ detail: { value } }) => onChange('max_prompt_length', value)}
                    />
                  </FormField>
                  <FormField
                    label={t("max_response_length")}
                    description="Max response length."
                    stretch={false}
                  >
                    <Input readOnly={readOnly}
                      value={readOnly ? data.job_payload?.max_response_length : data.max_response_length}
                      onChange={({ detail: { value } }) => onChange('max_response_length', value)}
                    />
                  </FormField>
                  </Grid>
                  <FormField
                    label={t("format_prompt")}
                    description={t("format_prompt")}
                    stretch={false}
                  >
                    <SelectFormatPromptType data={data} setData={setData} readOnly={readOnly} refs={refs}/>
                  </FormField>

              </SpaceBetween>
            </Container>
            <Container
              header={<Header variant="h2">{t("trainer_settings")}</Header>}
            >
            <SpaceBetween size="l">
            <Grid gridDefinition={[{ colspan: { "default": 4, xxs: 4 } }, { colspan: { "default": 4, xxs: 4 } },
                  ]}>
                  <FormField
                    label={t("total_epochs")}
                    description="Total training epochs."
                    stretch={false}
                  >
                    <Input readOnly={readOnly}
                      value={readOnly ? data.job_payload?.total_epochs : data.total_epochs}
                      onChange={({ detail: { value } }) => onChange('total_epochs', value)}
                    />
                  </FormField>
                  <FormField
                    label={t("max_steps")}
                    description="Max steps."
                    stretch={false}
                  >
                    <Input readOnly={readOnly}
                      value={readOnly ? data.job_payload?.max_steps : data.max_steps}
                      onChange={({ detail: { value } }) => onChange('max_steps', value)}
                    />
                  </FormField>
                </Grid>
                <Grid gridDefinition={[{ colspan: { "default": 4, xxs: 4 } }, { colspan: { "default": 4, xxs: 4 } },
                  ]}>
              <FormField
                label={t('save_freq')}
                description="Number of steps between two checkpoints."
                stretch={false}
              >
                <Input readOnly={readOnly}
                  value={readOnly ? data.job_payload?.save_freq : data.save_freq}
                  onChange={({ detail: { value } }) => onChange('save_freq', value)}
                />
              </FormField>
               <FormField
                label={t('val_freq')}
                description="Number of validataion steps between two checkpoints."
                stretch={false}
              >
                <Input readOnly={readOnly}
                  value={readOnly ? data.job_payload?.val_freq : data.val_freq}
                  onChange={({ detail: { value } }) => onChange('val_freq', value)}
                />
              </FormField>
                  </Grid>
                  <Grid gridDefinition={[{ colspan: { "default": 4, xxs: 4 } }, { colspan: { "default": 4, xxs: 4 } },
                ]}>
                  <FormField
                    label="Global batch size"
                    description="用于更新policy model的batch大小"
                    stretch={false}
                  >
                    <Input readOnly={readOnly}
                      value={readOnly ? data.job_payload?.global_batch_size : data.global_batch_size}
                      onChange={({ detail: { value } }) => onChange('global_batch_size', value)}
                    />
                  </FormField>
                  <FormField
                    label="Validation temperature"
                    description="用于推理验证集时模型采样温度"
                    stretch={false}
                  >
                    <Input readOnly={readOnly}
                      value={readOnly ? data.job_payload?.val_temperature : data.val_temperature}
                      onChange={({ detail: { value } }) => onChange('val_temperature', value)}
                    />
                  </FormField>
                  </Grid>
            </SpaceBetween>

            </Container>

            <Container
              header={<Header variant="h2">{t("worker_settings")}</Header>}
            >
              <SpaceBetween size="l">
              <Grid gridDefinition={[{ colspan: { "default": 4, xxs: 4 } }, { colspan: { "default": 4, xxs: 4 } },
                  ]}>
              <FormField
                label="Rollout tensor parallel size"
                description="tensor parallel size for rollout stage"
                stretch={false}
              >
                <Input readOnly={readOnly}
                  value={readOnly ? data.job_payload?.rollout_tensor_parallel_size : data.rollout_tensor_parallel_size}
                  onChange={({ detail: { value } }) => onChange('rollout_tensor_parallel_size', value)}
                />
              </FormField>
              <FormField
                label="Rollout limit images"
                description="vllm parameters, if use VLM, need to set >0"
                stretch={false}
              >
                <Input readOnly={readOnly}
                  value={readOnly ? data.job_payload?.limit_images : data.limit_images}
                  onChange={({ detail: { value } }) => onChange('limit_images', value)}
                />
              </FormField>
              </Grid>
              <Grid gridDefinition={[{ colspan: { "default": 4, xxs: 4 } }, { colspan: { "default": 4, xxs: 4 } },
                  ]}>
              <FormField
                label="Rollout batch size"
                description="一次Rollout的batch大小，建议与Global batch size保持4:1或者2:1"
                stretch={false}
              >
                <Input readOnly={readOnly}
                  value={readOnly ? data.job_payload?.rollout_batch_size : data.rollout_batch_size}
                  onChange={({ detail: { value } }) => onChange('rollout_batch_size', value)}
                />
              </FormField>
              <FormField
                    label="Rollout number"
                    description="每条prompt rollout采样条数"
                    stretch={false}
                  >
                    <Input readOnly={readOnly}
                      value={readOnly ? data.job_payload?.rollout_num : data.rollout_num}
                      onChange={({ detail: { value } }) => onChange('rollout_num', value)}
                    />
              </FormField>
              </Grid>
              <Grid gridDefinition={[{ colspan: { "default": 4, xxs: 4 } }, { colspan: { "default": 4, xxs: 4 } },
                  ]}>
              <FormField
                    label="Mini Rollout batch size"
                    description="把rollout batch再切分成小的batch"
                    stretch={false}
                  >
                    <Input readOnly={readOnly}
                      value={readOnly ? data.job_payload?.mini_rollout_batch_size : data.mini_rollout_batch_size}
                      onChange={({ detail: { value } }) => onChange('mini_rollout_batch_size', value)}
                    />
              </FormField>
              <FormField
                    label="Clip ratio low"
                    description="DAPO时使用"
                    stretch={false}
                  >
                    <Input readOnly={readOnly}
                      value={readOnly ? data.job_payload?.clip_ratio_low : data.clip_ratio_low}
                      onChange={({ detail: { value } }) => onChange('clip_ratio_low', value)}
                    />
              </FormField>
              </Grid>
              <Grid gridDefinition={[{ colspan: { "default": 4, xxs: 4 } }, { colspan: { "default": 4, xxs: 4 } },
                  ]}>
              <FormField
                    label="Clip ratio high"
                    description="DAPO时使用"
                    stretch={false}
                  >
                    <Input readOnly={readOnly}
                      value={readOnly ? data.job_payload?.clip_ratio_high : data.clip_ratio_high}
                      onChange={({ detail: { value } }) => onChange('clip_ratio_high', value)}
                    />
              </FormField>     
               </Grid>
              <Grid gridDefinition={[{ colspan: { "default": 4, xxs: 4 } }, { colspan: { "default": 4, xxs: 4 } },
                  ]}>
                <FormField
                  label="Offload params"
                  description="GPU显存不够时开启，在rollout时，卸载权重到cpu内存，会减少GPU显存消耗，但是影响速度，需要更多cpu内存"
                  stretch={false}
                >
                  <Toggle
                    readOnly={readOnly}
                    checked={readOnly ? data.job_payload?.offload_params : data.offload_params}
                    onChange={({ detail: { checked } }) => onChange('offload_params', checked)}
                  >
                    {t("enable")}
                  </Toggle>
                </FormField>
                <FormField
                  label="Offload optimizer"
                  description="GPU显存不够时开启，在rollout时，卸载优化器参数到cpu内存，会减少GPU显存消耗，但是影响速度，需要更多cpu内存"
                  stretch={false}
                >
                  <Toggle
                    readOnly={readOnly}
                    checked={readOnly ? data.job_payload?.offload_optimizer : data.offload_optimizer}
                    onChange={({ detail: { checked } }) => onChange('offload_optimizer', checked)}
                  >
                    {t("enable")}
                  </Toggle>
                  </FormField>
              </Grid>  
              
              <FormField
                label={t('reward_score_function')}
                description={<div>{t('reward_score_function_desc')}
                <Link external href={"https://github.com/hiyouga/EasyR1/tree/main/examples/reward_function"} >{t('reference_code')}</Link>
                </div>}
                stretch={false}
              >
               <SelectRewardFunction data={data} setData={setData} readOnly={readOnly} refs={refs}/>
              </FormField>
              { (data.job_payload?.reward_function === 'customize' || data.reward_function === 'customize') &&
              <FormField 
                label={t('customize_reward_score_function')}
                description={<div>
                <Link external href={"https://github.com/hiyouga/EasyR1/blob/main/examples/reward_function/math.py"} >{t('reference_code')}</Link>
                </div>}
                stretch={false}
                >
                <PythonEditor      
                 readOnly={readOnly}
                value={readOnly ? data.job_payload?.customize_reward_function : data.customize_reward_function}
                onDelayedChange={(event) => onChange('customize_reward_function', event.detail.value)}
                /> 
              </FormField>
            }
              </SpaceBetween>
            </Container>

            <Container
              header={<Header variant="h2">{t("training_instance_settings")}</Header>}
            >
              <SpaceBetween size="l">
                <FormField
                  label={t('instance_type')}
                  description="Selecte a instance type for training."
                  stretch={false}
                  errorText={errors.instance_type}
                  i18nStrings={{ errorIconAriaLabel: 'Error' }}
                >
                  <SelectInstanceType data={data} setData={setData} readOnly={readOnly} refs={refs} />
                </FormField>
                <FormField
                  label={t('instance_amount')}
                  description="Set the instance amount"
                  stretch={false}
                  errorText={errors.instance_num}
                  i18nStrings={{ errorIconAriaLabel: 'Error' }}
                >
                  <Input readOnly={readOnly}
                    value={readOnly ? data.job_payload.instance_num : data.instance_num}
                    ref={refs.instance_num}
                    onChange={({ detail: { value } }) => onChange('instance_num', value)}
                  />
                </FormField>
                <FormField
                  label={t("training_plan")}
                  description={t("use_training_plan")}
                  stretch={false}
                >
                  <Input readOnly={readOnly}
                    value={readOnly ? data.job_payload.training_plan : data.training_plan}
                    ref={refs.training_plan}
                    onChange={({ detail: { value } }) => onChange('training_plan', value)}
                  />
                </FormField>
                <FormField
                  label={t("use_spot")}
                  description={t("use_spot_desc")}
                  stretch={false}
                >
                  <Toggle
                    readOnly={readOnly}
                    checked={readOnly ? data.job_payload?.use_spot : data.use_spot}
                    onChange={({ detail: { checked } }) => onChange('use_spot', checked)}
                  >
                    {t("enable")}
                  </Toggle>
                </FormField>
                <FormField
                  label={t("max_spot_wait")}
                  description={t("max_spot_wait_desc")}
                  stretch={false}
                >
                  <Input readOnly={readOnly}
                    value={readOnly ? data.job_payload?.max_spot_wait : data.max_spot_wait}
                    onChange={({ detail: { value } }) => onChange('max_spot_wait', value)}
                  />
                </FormField>
              </SpaceBetween>
            </Container>
          </SpaceBetween>
      )    
  }

const LFJobSetting = ({ validation,
  onChange,
  readOnly,
  data,
  errors,
  setData,
  setErrors,
  refs }) => {

  return (<SpaceBetween size="xl" direction="vertical">
    <Container
      header={<Header variant="h2">{t('training_job_settings')}</Header>}
    >
      <SpaceBetween size="l">
        <FormField
          label={t('model_name')}
          stretch={false}
          description="选择模型"
          errorText={errors.model_name}
          i18nStrings={{ errorIconAriaLabel: 'Error' }}
        >
          <SelectModelName data={data} setData={setData} readOnly={readOnly} refs={refs} />
        </FormField>
        <FormField
          label="使用已有的模型权重进行训练 (Optional)"
          stretch={false}
          description="使用已有的模型文件进行训练"
          errorText={errors.s3_model_path}
          i18nStrings={{ errorIconAriaLabel: 'Error' }}
        >
          <S3Selector
            readOnly={readOnly}
            objectsIsItemDisabled={(item) => !item.IsFolder}
            setOutputPath={(value) => setData({ s3_model_path: value })}
            outputPath={readOnly ? data.job_payload?.s3_model_path : data.s3_model_path} />
        </FormField>
        <FormField
          label="使用已有的Checkpoint (Optional)"
          stretch={false}
          description="使用已有的checkpoint文件继续训练（⚠️：如果是Lora训练，选择Lora模型checkpoint）"
          errorText={errors.s3_checkpoint}
          i18nStrings={{ errorIconAriaLabel: 'Error' }}
        >
          <S3Selector
            readOnly={readOnly}
            objectsIsItemDisabled={(item) => !item.IsFolder}
            setOutputPath={(value) => setData({ s3_checkpoint: value })}
            outputPath={readOnly ? data.job_payload?.s3_checkpoint : data.s3_checkpoint} />
        </FormField>
        <FormField
          label="选择Chat Template"
          description="select a Chat Template to format the dataset"
          stretch={false}
          errorText={errors.prompt_template}
          i18nStrings={{ errorIconAriaLabel: 'Error' }}
        >
          <SelectPromptTemplate data={data} setData={setData} readOnly={readOnly} refs={refs} />
        </FormField>
        <FormField
          label={t('finetuning_method')}
          description="Choose Finetuning method for the job"
          stretch={true}
        >
          <RadioGroup
            items={FT_OPTIONS}
            readOnly={readOnly}
            value={readOnly ? data.job_payload?.finetuning_method : data.finetuning_method}
            onChange={({ detail: { value } }) => onChange('finetuning_method', value)}
            ref={refs.finetuning_method}
          />
        </FormField>
        {/* <FormField
          label="Quantization bit"
          description="Enable 4/8-bit model quantization (QLoRA)."
          stretch={true}
        >
          <RadioGroup
            items={QUANT_OPTIONS}
            readOnly={readOnly}
            value={readOnly ? data.job_payload?.quantization_bit : data.quantization_bit}
            onChange={({ detail: { value } }) => onChange('quantization_bit', value)}
            ref={refs.quantization_bit}
          />
        </FormField> */}
        <FormField
          label="Booster Option"
          stretch={true}
        >
          <RadioGroup
            items={BOOSTER_OPTIONS}
            readOnly={readOnly}
            value={readOnly ? data.job_payload?.booster_option : data.booster_option}
            onChange={({ detail: { value } }) => onChange('booster_option', value)}
            ref={refs.booster_option}
          />
        </FormField>
        <FormField
          label={t("max_job_run_hour")}
          description={t("max_job_run_hour_desc")}
          stretch={false}
        >
          <Input readOnly={readOnly}
            value={readOnly ? data.job_payload?.max_job_run_hour : data.max_job_run_hour}
            onChange={({ detail: { value } }) => onChange('max_job_run_hour', value)}
          />
        </FormField>
      </SpaceBetween>
    </Container>
    <Container
      header={<Header variant="h2">{t('datasets_settings')}</Header>}
    >
      <SpaceBetween size="l">
        <FormField
          label="Training Data in S3"
          stretch={false}
          description="Input the S3 path of your own dataset"
          errorText={errors.s3DataPath}
          i18nStrings={{ errorIconAriaLabel: 'Error' }}
        >
          <S3Selector label={"S3 Data Path"}
            readOnly={readOnly}
            objectsIsItemDisabled={(item) => !item.IsFolder}
            setOutputPath={(value) => setData({ s3DataPath: value })}
            outputPath={readOnly ? data.job_payload?.s3_data_path : data.s3DataPath} />
        </FormField>
        {(data.job_payload?.s3_data_path || data.s3DataPath) &&
          <FormField
            label="Dataset Info"
            description="Need to prepare a data set info in Json format. For example"
            stretch={false}
          >
            <JsonEditor
              readOnly={readOnly}
              value={readOnly ? data.job_payload?.dataset_info : data.datasetInfo}
              onDelayedChange={(event) => onChange('datasetInfo', event.detail.value)}
            />
          </FormField>}

        <FormField
          label={t("public_datasets")}
          stretch={false}
          description="select open-source datasets from hf"
          errorText={errors.dataset}
          i18nStrings={{ errorIconAriaLabel: 'Error' }}
        >
          <SelectDatasets data={data} setData={setData} readOnly={readOnly} refs={refs} />
        </FormField>
        <Grid gridDefinition={[{ colspan: { "default": 4, xxs: 4 } }, { colspan: { "default": 4, xxs: 4 } },
        ]}>
          <FormField
            label="Max samples"
            description="Maximum samples per dataset."
            stretch={false}
          >
            <Input readOnly={readOnly}
              value={readOnly ? data.job_payload?.max_samples : data.max_samples}
              onChange={({ detail: { value } }) => onChange('max_samples', value)}
            />
          </FormField>
          <FormField
            label="Cutoff length"
            description="Max tokens in input sequence."
            stretch={false}
          >
            <Input readOnly={readOnly}
              value={readOnly ? data.job_payload?.cutoff_len : data.cutoff_len}
              onChange={({ detail: { value } }) => onChange('cutoff_len', value)}
            />
          </FormField>
        </Grid>
        <Grid gridDefinition={[{ colspan: { "default": 4, xxs: 4 } }]}>
          <FormField
            label="Val size"
            description="Proportion of data in the dev set."
            stretch={false}
          >
            <Input readOnly={readOnly}
              value={readOnly ? data.job_payload?.val_size : data.val_size}
              onChange={({ detail: { value } }) => onChange('val_size', value)}
            />
          </FormField>
        </Grid>
      </SpaceBetween>
    </Container>
    <Container
      header={<Header variant="h2">{t("training_instance_settings")}</Header>}
      footer={<DeepSpeedConfigs data={data} onChange={onChange} readOnly={readOnly} setData={setData} />}
    >
      <SpaceBetween size="l">
        <FormField
          label={t('instance_type')}
          description="Selecte a instance type for training."
          stretch={false}
          errorText={errors.instance_type}
          i18nStrings={{ errorIconAriaLabel: 'Error' }}
        >
          <SelectInstanceType data={data} setData={setData} readOnly={readOnly} refs={refs} />
        </FormField>
        <FormField
          label={t('instance_amount')}
          description="Set the instance amount"
          stretch={false}
          errorText={errors.instance_num}
          i18nStrings={{ errorIconAriaLabel: 'Error' }}
        >
          <Input readOnly={readOnly}
            value={readOnly ? data.job_payload.instance_num : data.instance_num}
            ref={refs.instance_num}
            onChange={({ detail: { value } }) => onChange('instance_num', value)}
          />
        </FormField>
          <FormField
              label={t("training_plan")}
              description={t("use_training_plan")}
              stretch={false}
            >
              <Input readOnly={readOnly}
                value={readOnly ? data.job_payload.training_plan : data.training_plan}
                ref={refs.training_plan}
                onChange={({ detail: { value } }) => onChange('training_plan', value)}
              />
            </FormField>
        <FormField
          label={t("use_spot")}
          description={t("use_spot_desc")}
          stretch={false}
        >
          <Toggle
            readOnly={readOnly}
            checked={readOnly ? data.job_payload?.use_spot : data.use_spot}
            onChange={({ detail: { checked } }) => onChange('use_spot', checked)}
          >
            {t("enable")}
          </Toggle>
        </FormField>
        <FormField
          label={t("max_spot_wait")}
          description={t("max_spot_wait_desc")}
          stretch={false}
        >
          <Input readOnly={readOnly}
            value={readOnly ? data.job_payload?.max_spot_wait : data.max_spot_wait}
            onChange={({ detail: { value } }) => onChange('max_spot_wait', value)}
          />
        </FormField>
      </SpaceBetween>
    </Container>
    <Container header={<Header variant="h2">{t("hyper_params_settings")}</Header>}
      footer={<AdvancedConfigs data={data} onChange={onChange} readOnly={readOnly} setData={setData} />}
    >
      <SpaceBetween size="l">
        <Grid gridDefinition={[{ colspan: { "default": 6, xxs: 4 } }, { colspan: { "default": 6, xxs: 4 } }]}>
          <FormField
            label="Learning rate"
            description="Initial learning rate for AdamW."
            stretch={false}
          >
            <Input readOnly={readOnly}
              value={readOnly ? data.job_payload?.learning_rate : data.learning_rate}
              onChange={({ detail: { value } }) => onChange('learning_rate', value)}
            />
          </FormField>
          <FormField
            label="Epoch"
            description="Total number of training epochs to perform."
            stretch={false}
          >
            <Input readOnly={readOnly}
              value={readOnly ? data.job_payload?.num_train_epochs : data.num_train_epochs}
              onChange={({ detail: { value } }) => onChange('num_train_epochs', value)}
            />
          </FormField>
        </Grid>
        <Grid gridDefinition={[{ colspan: { "default": 6, xxs: 4 } }, { colspan: { "default": 6, xxs: 4 } }]}>
          <FormField
            label="Batch size per device"
            description="Number of samples processed on each GPU."
            stretch={false}
          >
            <Input readOnly={readOnly}
              value={readOnly ? data.job_payload?.per_device_train_batch_size : data.per_device_train_batch_size}
              onChange={({ detail: { value } }) => onChange('per_device_train_batch_size', value)}
            />
          </FormField>
          <FormField
            label="Gradient accumulation"
            description="Number of steps for gradient accumulation."
            stretch={false}
          >
            <Input readOnly={readOnly}
              value={readOnly ? data.job_payload?.gradient_accumulation_steps : data.gradient_accumulation_steps}
              onChange={({ detail: { value } }) => onChange('gradient_accumulation_steps', value)}
            />
          </FormField>
        </Grid>
        <Grid gridDefinition={[{ colspan: { "default": 6, xxs: 4 } }, { colspan: { "default": 6, xxs: 4 } }]}>
          <FormField
            label="Training precision"
            description="Whether to use mixed precision training."
            stretch={false}
          >
            <SelectTrainingPrecision data={data} readOnly={readOnly} setData={setData} />
          </FormField>
        </Grid>
      </SpaceBetween>
    </Container>
    </SpaceBetween>
  )
}

export default function DistributionPanel({
  loadHelpPanelContent,
  validation = false,
  readOnly = false,
  data,
  errors = {},
  setData,
  setErrors,
  setNotificationData,
  setDisplayNotify,
  setReadOnly,
  refs = {},
}) {

  const onChange = (attribute, value) => {
    setData({ [attribute]: value });

    // Validates when there is an error message in the field
    if (validation && errors[attribute]?.length > 0) {
      const { errorText } = validateField(attribute, value);
      setErrors({ [attribute]: errorText });
    }
  };


  const onBlur = attribute => {
    if (!validation) {
      return;
    }

    const value = data[attribute];
    const { errorText } = validateField(attribute, value);

    setErrors({ [attribute]: errorText });
  };

  useEffect(() => {
    //遍历data.job_payload中的所有元素，并setData({ [attribute]: value })
    if (data.job_payload) {
      Object.entries(data.job_payload).forEach(([attribute, value]) => {
        setData({ [attribute]: value });
      });
      setData({
        job_name: data.job_name
      });
      setData({
        stage: data.job_type
      });
      setData({
        s3DataPath: data.job_payload.s3_data_path
      });
      setData({
        datasetInfo: data.job_payload.dataset_info
      });
      setData({
        datasetInfo2: data.job_payload.dataset_info2
      });
    }
    console.log('init data:', data);

  }, [])

  return (
    <SpaceBetween size="xl" direction="vertical">
      <Container
        header={<Header variant="h2">{t('basic_info')}</Header>}
      >
        <SpaceBetween size="l">
          <FormField
            label={t('job_name')}
            description="Give a name to your job."
            stretch={false}
            errorText={errors.job_name}
            i18nStrings={{ errorIconAriaLabel: 'Error' }}
          >
            <Input readOnly={readOnly}
              value={data.job_name}
              onChange={({ detail: { value } }) => onChange('job_name', value)}
              placeholder="Give a name to your job"
              ref={refs.job_name}
              onBlur={() => onBlur('job_name')}
            />
          </FormField>

          <FormField
            label={t('train_stage')}
            description="The stage to perform in training."
            stretch={false}
            errorText={errors.stage}
            i18nStrings={{ errorIconAriaLabel: 'Error' }}
          >
            <SelectStage data={data} setData={setData} readOnly={readOnly} refs={refs} />
          </FormField>
        </SpaceBetween>
      </Container>

      {data.stage === 'grpo'|| data.stage === 'dapo' ?
        <EasyR1JobSetting onChange={onChange} validation={validation} readOnly={readOnly} data={data} errors={errors} setData={setData} refs={refs} />
        :
        <LFJobSetting onChange={onChange} validation={validation} readOnly={readOnly} data={data} errors={errors} setData={setData} refs={refs} />
      }
    </SpaceBetween>
  );
}
