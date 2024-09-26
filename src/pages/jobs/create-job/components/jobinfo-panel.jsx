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
  Box,
  Multiselect,
  Toggle,
} from '@cloudscape-design/components';
import { FT_OPTIONS, QUANT_OPTIONS, TRAINING_STAGES, TRAINING_PRECISION,OPTMIZERS,INSTANCE_TYPES,BOOSTER_OPTIONS, DEEPSPEED } from '../form-config';
import validateField from '../form-validation-config';
import { remotePost } from '../../../../common/api-gateway';
import {S3Selector} from './output-path';
import { JsonEditor } from './code-editor';
import { t } from 'i18next';


function AdvancedConfigs({ onChange, readOnly, data,setData }) {
  return (
  <SpaceBetween size="l"> 
    <ExpandableSection headerText="Extra configurations" variant="footer">
      <Grid
        gridDefinition={[ { colspan: { default: 6, xxs: 4 } },{ colspan: { default: 6, xxs: 4 } }]}
      >
        <FormField
          label="Warmup steps"
          description="Number of steps used for warmup."
          stretch={false}
        >
          <Input readOnly={readOnly}
            value={data.job_payload ? data.job_payload.warmup_steps : data.warmup_steps}
            onChange={({ detail: { value } }) => onChange('warmup_steps', value)}
          />
        </FormField>
        <FormField
          label="Logging steps"
          description="Number of steps between two logs."
          stretch={false}
        >
          <Input readOnly={readOnly}
            value={data.job_payload ? data.job_payload.logging_steps : data.logging_steps}
            onChange={({ detail: { value } }) => onChange('logging_steps', value)}
          />
        </FormField>
      </Grid>
      <Grid
        gridDefinition={[ { colspan: { default: 6, xxs: 4 } },{ colspan: { default: 6, xxs: 4 } }]}
      >
        <FormField
          label="Save steps"
          description="Number of steps between two checkpoints."
          stretch={false}
        >
          <Input readOnly={readOnly}
            value={data.job_payload ? data.job_payload.save_steps : data.save_steps}
            onChange={({ detail: { value } }) => onChange('save_steps', value)}
          />
        </FormField>
        <FormField
          label="Optimizer"
          description="The optimizer to use."
          stretch={false}
        >
          <SelectOptimizer readOnly={readOnly} data={data} setData={setData}/>
        </FormField>
      </Grid>

    </ExpandableSection>
    <ExpandableSection headerText="Lora configurations" variant="footer">
    <Grid
        gridDefinition={[ { colspan: { default: 6, xxs: 4 } },{ colspan: { default: 6, xxs: 4 } }]}
      >
        <FormField
          label="LoRA rank"
          description="The rank of LoRA matrices."
          stretch={false}
        >
          <Input readOnly={readOnly}
            value={data.job_payload ? data.job_payload.lora_rank : data.lora_rank}
            onChange={({ detail: { value } }) => onChange('lora_rank', value)}
          />
        </FormField>
        <FormField
          label="LoRA alpha"
          description="Lora scaling coefficient."
          stretch={false}
        >
          <Input readOnly={readOnly}
            value={data.job_payload ? data.job_payload.lora_alpha : data.lora_alpha}
            onChange={({ detail: { value } }) => onChange('lora_alpha', value)}
          />
        </FormField>
      </Grid>
      </ExpandableSection>
 </SpaceBetween> 
  );
}

function DeepSpeedConfigs({ onChange, readOnly, data,setData }) {
  return (
  <SpaceBetween size="l"> 
    <ExpandableSection headerText="DeepSpeed configurations (Applicable for Multi-GPU/Nodes)" variant="footer" expanded>
      <Grid
        gridDefinition={[ { colspan: { default: 6, xxs: 4 } },{ colspan: { default: 6, xxs: 4 } }]}
      >
        <FormField
          label="DeepSpeed Stage"
          description="DeepSpeed stage for distributed training."
          stretch={false}
        >
          <RadioGroup
              items={DEEPSPEED}
              value={data.job_payload ? data.job_payload.deepspeed : data.deepspeed}
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
  // const initState = data.job_payload ? { label: data.job_payload.model_name, value: data.job_payload.model_name } : {};
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

  const initState = data.job_payload &&data.job_payload.dataset? data.job_payload.dataset.map(item => ({
    label: item, value: item
  })) : []
  // const [selectOption, setSelectOption] = useState(initState);

  const [selectedOptions, setSelectOptions] = useState(initState);
  const handleLoadItems = async ({
    detail: { filteringText, firstPage, samePage },
  }) => {
    setLoadStatus("loading");
    try {
      const data = await remotePost({ config_name: 'dataset' }, 'get_factory_config');
      const items = data.response.body.map((it) => ({
        dataset: it,
      }));
      setItems(items);
      setLoadStatus("finished");
    } catch (error) {
      console.log(error);
      setLoadStatus("error");
    }
  };
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

const SelectBooster = ({ data, setData, readOnly, refs }) => {
  const initState = BOOSTER_OPTIONS.filter(item => data.job_payload?.booster_option === item.value)
  const [selectOption, setSelectOption] = useState(initState.length ? initState[0] : BOOSTER_OPTIONS[0]);
  return (
    <Select
      selectedOption={selectOption}
      disabled={readOnly}
      onChange={({ detail }) => {
        setSelectOption(detail.selectedOption);
        setData({ booster_option: detail.selectedOption.value })
      }}
      options={BOOSTER_OPTIONS}
      selectedAriaLabel="Selected"
    />
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

  return (
    <SpaceBetween size="xl" direction="vertical">
      <Container
        header={<Header variant="h2">Training job settings</Header>}
      >
        <SpaceBetween size="l">
          <FormField
            label="Job Name"
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
            label="Train Stage"
            description="The stage to perform in training."
            stretch={false}
            errorText={errors.stage}
            i18nStrings={{ errorIconAriaLabel: 'Error' }}
          >
            <SelectStage data={data} setData={setData} readOnly={readOnly} refs={refs} />
          </FormField>
          <FormField
            label="Model Name"
            stretch={false}
            description="选择模型名称"
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
                      objectsIsItemDisabled={(item) => !item.IsFolder}
                      setOutputPath={(value)=> setData({ s3_model_path:value})} 
                    outputPath={data.job_payload?.s3_model_path|| data.s3_model_path}/>
          </FormField>
          <FormField
            label="Use Existing Checkpoint (Optional)"
            stretch={false}
            description="使用已有的checkpoint文件继续训练（⚠️：如果是Lora训练，选择Lora模型checkpoint）"
            errorText={errors.s3_checkpoint}
            i18nStrings={{ errorIconAriaLabel: 'Error' }}
          >
            <S3Selector 
                    objectsIsItemDisabled={(item) => !item.IsFolder}
                    setOutputPath={(value)=> setData({ s3_checkpoint:value})} 
                  outputPath={data.job_payload?.s3_checkpoint|| data.s3_checkpoint}/>
          </FormField>
          
          <FormField
            label="Prompte Template"
            description="select a Prompt Template to format the dataset"
            stretch={false}
            errorText={errors.prompt_template}
            i18nStrings={{ errorIconAriaLabel: 'Error' }}
          >
            <SelectPromptTemplate data={data} setData={setData} readOnly={readOnly} refs={refs} />
          </FormField>
          <FormField
            label="Finetuning method"
            description="Choose Finetuning method for the job"
            stretch={true}
          >
            <RadioGroup
              items={FT_OPTIONS}
              value={data.job_payload ? data.job_payload.finetuning_method : data.finetuning_method}
              onChange={({ detail: { value } }) => onChange('finetuning_method', value)}
              ref={refs.finetuning_method}
            />
          </FormField>
          <FormField
            label="Quantization bit"
            description="Enable 4/8-bit model quantization (QLoRA)."
            stretch={true}
          >
            <RadioGroup
              items={QUANT_OPTIONS}
              value={data.job_payload ? data.job_payload.quantization_bit : data.quantization_bit}
              onChange={({ detail: { value } }) => onChange('quantization_bit', value)}
              ref={refs.quantization_bit}
            />
          </FormField>
          <FormField
            label="Booster Option"
            stretch={true}
          >
            <RadioGroup
              items={BOOSTER_OPTIONS}
              value={data.job_payload ? data.job_payload.booster_option : data.booster_option}
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
            value={data.job_payload ? data.job_payload.max_job_run_hour : data.max_job_run_hour}
            onChange={({ detail: { value } }) => onChange('max_job_run_hour', value)}
          />
          </FormField>
        </SpaceBetween>
      </Container>
      <Container
        header={<Header variant="h2">Datasets settings</Header>}
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
                    objectsIsItemDisabled={(item) => !item.IsFolder}
                    setOutputPath={(value)=> setData({ s3DataPath:value})} 
                  outputPath={data.job_payload?.s3_data_path|| data.s3DataPath}/>
          </FormField>
          {(data.job_payload?.s3_data_path|| data.s3DataPath) &&
          <FormField
              label="Dataset Info"
              description="Need to prepare a data set info in Json format. For example"
              stretch={false}
            >
                <JsonEditor 
                readOnly={readOnly}
                value={data.job_payload?.dataset_info || data.datasetInfo}
                onDelayedChange={(event) => onChange('datasetInfo', event.detail.value)}
                />
          </FormField>}

         <FormField
            label="Public Datesets"
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
                value={data.job_payload ? data.job_payload.max_samples : data.max_samples}
                onChange={({ detail: { value } }) => onChange('max_samples', value)}
              />
            </FormField>
            <FormField
              label="Cutoff length"
              description="Max tokens in input sequence."
              stretch={false}
            >
              <Input readOnly={readOnly}
                value={data.job_payload ? data.job_payload.cutoff_len : data.cutoff_len}
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
                value={data.job_payload ? data.job_payload.val_size : data.val_size}
                onChange={({ detail: { value } }) => onChange('val_size', value)}
              />
            </FormField>
          </Grid>
        </SpaceBetween>
      </Container>
      <Container
        header={<Header variant="h2">Training Instances settings</Header>}
        footer={<DeepSpeedConfigs data={data} onChange={onChange} readOnly={readOnly} setData={setData}/>}
      >
        <SpaceBetween size="l">
          <FormField
            label="Instances Type"
            description="Selecte a instance type for training."
            stretch={false}
            errorText={errors.instance_type}
            i18nStrings={{ errorIconAriaLabel: 'Error' }}
          >
            <SelectInstanceType  data={data} setData={setData} readOnly={readOnly} refs={refs}/>
          </FormField>
          <FormField
            label="Instances amount"
            description="Set the instance amount"
            stretch={false}
            errorText={errors.instance_num}
            i18nStrings={{ errorIconAriaLabel: 'Error' }}
          >
            <Input readOnly={readOnly}
            value={data.job_payload ? data.job_payload.instance_num : data.instance_num}
            ref={refs.instance_num}
            onChange={({ detail: { value } }) => onChange('instance_num', value)}
          />
          </FormField>
          <FormField
            label={t("use_spot")}
            description={t("use_spot_desc")}
            stretch={false}
          >
            <Toggle
              readOnly={readOnly}
              checked={data.job_payload ? data.job_payload.use_spot : data.use_spot}
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
            value={data.job_payload ? data.job_payload.max_spot_wait : data.max_spot_wait}
            onChange={({ detail: { value } }) => onChange('max_spot_wait', value)}
          />
          </FormField>
        </SpaceBetween>
      </Container>
      <Container header={<Header variant="h2">Hyper params settings</Header>}
        footer={<AdvancedConfigs data={data} onChange={onChange} readOnly={readOnly} setData={setData}/>}
      >
        <SpaceBetween size="l">
        <Grid gridDefinition={[{ colspan: { "default": 6, xxs: 4 } }, { colspan: { "default": 6, xxs: 4 } }]}>
          <FormField
            label="Learning rate"
            description="Initial learning rate for AdamW."
            stretch={false}
          >
            <Input readOnly={readOnly}
              value={data.job_payload ? data.job_payload.learning_rate : data.learning_rate}
              onChange={({ detail: { value } }) => onChange('learning_rate', value)}
            />
          </FormField>
          <FormField
            label="Epoch"
            description="Total number of training epochs to perform."
            stretch={false}
          >
            <Input readOnly={readOnly}
              value={data.job_payload ? data.job_payload.num_train_epochs : data.num_train_epochs}
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
              value={data.job_payload ? data.job_payload.per_device_train_batch_size : data.per_device_train_batch_size}
              onChange={({ detail: { value } }) => onChange('per_device_train_batch_size', value)}
            />
          </FormField>
          <FormField
            label="Gradient accumulation"
            description="Number of steps for gradient accumulation."
            stretch={false}
          >
            <Input readOnly={readOnly}
              value={data.job_payload ? data.job_payload.gradient_accumulation_steps : data.gradient_accumulation_steps}
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
  );
}
