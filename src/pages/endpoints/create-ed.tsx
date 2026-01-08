// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { useEffect, useState } from 'react';
import {
  Button, Modal, Box, RadioGroup, RadioGroupProps, FormField,
  Link, Input, Alert,
  Toggle, SpaceBetween, Select, SelectProps
} from '@cloudscape-design/components';
import { remotePost, remoteGet } from '../../common/api-gateway';
import { useSimpleNotifications } from '../commons/use-notifications';
import { useNavigate } from "react-router-dom";
import { t } from 'i18next';
import {S3Selector} from '../jobs/create-job/components/output-path';


interface PageHeaderProps {
  extraActions?: React.ReactNode;
  selectedItems: ReadonlyArray<any>,
  visible: boolean;
  setVisible: (value: boolean) => void;
  setDisplayNotify: (value: boolean) => void;
  setNotificationData: (value: any) => void;
  onDelete?: () => void;
  onRefresh?: () => void;
}

interface SelectInstanceTypeProps {
  data: any;
  setData: (value: any) => void;
  readOnly: boolean;
  // refs?:Record<string,React.RefObject<any>>;
}
interface SelectQuantTypeProps {
  data: any;
  setData: (value: any) => void;
  readOnly: boolean;
}
interface SelectModelProps {
  data: any;
  setData: (value: any) => void;
  readOnly: boolean;
  // refs?:Record<string,React.RefObject<any>>;
}

const defaultErrors = {
  instance_type: null,
  engine: null,
  enable_lora: null,
  model_name: null,
  quantize: null,
  instance_count:null,
}

const HF_QUANT_TYPES = [
  { label: "None", value: "" },
  { label: "int8", value: "bitsandbytes8" },
  { label: "int4", value: "bitsandbytes4" },
]

const LMI_QUANT_TYPES = [
  { label: "None", value: "" },
  { label: "awq", value: "awq" },
  { label: "gptq", value: "gptq" },
]

const TRT_QUANT_TYPES = [
  { label: "None", value: "" },
  { label: "awq", value: "awq" },
  { label: "smoothquant", value: "smoothquant" },
]

const vLLM_QUANT_TYPES = [
  { label: "None", value: "" },
  { label: "awq", value: "awq" },
]

const INSTANCE_TYPES: SelectProps.Option[] = [
  { label: 'ml.g4dn.2xlarge', value: 'ml.g4dn.2xlarge' },
  { label: 'ml.g4dn.12xlarge', value: 'ml.g4dn.12xlarge' },
  { label: 'ml.g5.xlarge', value: 'ml.g5.xlarge' },
  { label: 'ml.g5.2xlarge', value: 'ml.g5.2xlarge' },
  { label: 'ml.g5.4xlarge', value: 'ml.g5.4xlarge' },
  { label: 'ml.g5.12xlarge', value: 'ml.g5.12xlarge' },
  { label: 'ml.g5.48xlarge', value: 'ml.g5.48xlarge' },
  { label: 'ml.g6.2xlarge', value: 'ml.g6.2xlarge' },
  { label: 'ml.g6.12xlarge', value: 'ml.g6.12xlarge' },
  { label: 'ml.g6.48xlarge', value: 'ml.g6.48xlarge' },
  { label: 'ml.g6e.2xlarge', value: 'ml.g6e.2xlarge' },
  { label: 'ml.g6e.12xlarge', value: 'ml.g6e.12xlarge' },
  { label: 'ml.g6e.48xlarge', value: 'ml.g6e.48xlarge' },
  { label: 'ml.p3.2xlarge', value: 'ml.p3.2xlarge' },
  { label: 'ml.p3.8xlarge', value: 'ml.p3.8xlarge' },
  { label: 'ml.p3.16xlarge', value: 'ml.p3.16xlarge' },
  { label: 'ml.p4d.24xlarge', value: 'ml.p4d.24xlarge' },
  { label: 'ml.p4de.24xlarge', value: 'ml.p4de.24xlarge' },
  { label: 'ml.p5.48xlarge', value: 'ml.p5.48xlarge' },
  { label: 'ml.p5e.48xlarge', value: 'ml.p5e.48xlarge' },
  { label: 'ml.p5en.48xlarge', value: 'ml.p5en.48xlarge' }
]

const ENGINE: RadioGroupProps.RadioButtonDefinition[] = [
  { label: 'vLLM', value: 'vllm' },
  { label: 'SGLang', value: 'sglang' },
]

const DEPLOYMENT_TARGETS: RadioGroupProps.RadioButtonDefinition[] = [
  { label: 'SageMaker Endpoint', value: 'sagemaker' },
  { label: 'HyperPod Cluster', value: 'hyperpod' },
]

const defaultData = {
  instance_type: '',
  engine: 'vllm',
  enable_lora: false,
  model_name: undefined,
  quantize: '',
  cust_repo_type: 'hf',
  cust_repo_addr: '',
  extra_params:{enable_prefix_caching:true},
  deployment_target: 'sagemaker',
  hyperpod_cluster_id: undefined,
  availableInstanceTypes: [] as string[],  // Available instance types from selected HyperPod cluster (for backward compatibility)
  instanceTypeDetails: [] as Array<{ instance_type: string; instance_groups: string[] }>,  // Detailed instance type info with instance groups
  hyperpod_config: {
    replicas: 1,
    namespace: 'default',
    enable_autoscaling: false,
    min_replicas: 1,
    max_replicas: 10,
    enable_kv_cache: false,
    enable_l2_cache: false,  // Disabled by default due to HyperPod operator bug (lmcache-config volume mount error)
    kv_cache_backend: 'tieredstorage',
    enable_intelligent_routing: false,
    routing_strategy: 'prefixaware',
    use_public_alb: false,
    // API Key authentication (required when public ALB is enabled)
    enable_api_key: false,
    api_key_source: 'auto',  // 'auto' (auto-generate), 'custom', 'secrets_manager'
    custom_api_key: '',
    secrets_manager_secret_name: ''
  }
}

const ROUTING_STRATEGIES: SelectProps.Option[] = [
  { label: 'Prefix Aware', value: 'prefixaware', description: 'Route based on prompt prefix (default)' },
  { label: 'KV Aware', value: 'kvaware', description: 'Real-time KV cache tracking for maximum cache hits' },
  { label: 'Session', value: 'session', description: 'Route based on user session for multi-turn conversations' },
  { label: 'Round Robin', value: 'roundrobin', description: 'Simple round-robin distribution' },
]

const KV_CACHE_BACKENDS: SelectProps.Option[] = [
  { label: 'Tiered Storage (Recommended)', value: 'tieredstorage', description: 'Distributed tiered storage cache' },
  { label: 'Redis', value: 'redis', description: 'Redis-based distributed cache' },
]

const API_KEY_SOURCES: SelectProps.Option[] = [
  { label: 'Auto Generate (Recommended)', value: 'auto', description: 'Automatically generate a secure API key' },
  { label: 'Custom API Key', value: 'custom', description: 'Provide your own API key' },
  { label: 'AWS Secrets Manager', value: 'secrets_manager', description: 'Use existing secret from AWS Secrets Manager' },
]

const instanceCalculator = process.env.REACT_APP_CALCULATOR;

const SelectModelName = ({ data, setData, readOnly }: SelectModelProps) => {
  // console.log(data)
  const [loadStatus, setLoadStatus] = useState<any>("loading");
  const [items, setItems] = useState([]);
  // const initState = data.job_payload ? { label: data.job_payload.model_name, value: data.job_payload.model_name } : {};
  const [selectOption, setSelectOption] = useState({});
  useEffect(() => {
    if (data.model_name) {
      setSelectOption({ label: data.model_name, value: data.model_name })
      setData((pre: any) => ({ ...pre, model_name: data.model_name }))
    }
  }, [data.model_name])
  const handleLoadItems = async ({
    detail: { },
  }) => {
    setLoadStatus("loading");
    try {
      const data = await remotePost({ config_name: 'model_name' }, 'get_factory_config');
      const items = data.response.body.map((it: any) => ({
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
        setData((pre: any) => ({ ...pre, model_name: detail.selectedOption.value }))
      }}
      options={items.map(({ model_name, model_path }) => ({
        label: model_name,
        value: model_path,
        tags: [model_path]
      }))}
      selectedAriaLabel="Selected"
    />
  )
}
const SelectInstanceType = ({ data, setData, readOnly }: SelectInstanceTypeProps) => {
  const [selectOption, setSelectOption] = useState<SelectProps.Option | null>(null);

  // Build options based on deployment target
  const availableOptions: SelectProps.Option[] = React.useMemo(() => {
    if (data.deployment_target === 'hyperpod') {
      // For HyperPod, use instanceTypeDetails to show instance groups and availability
      if (data.instanceTypeDetails?.length > 0) {
        return data.instanceTypeDetails.map((detail: {
          instance_type: string;
          instance_groups: string[];
          total_count?: number;
          running_count?: number;
          available_count?: number;
          is_available?: boolean;
        }) => {
          const isAvailable = detail.is_available !== false && (detail.available_count === undefined || detail.available_count > 0);
          const tags: string[] = [];

          // Add instance group info
          if (detail.instance_groups?.length > 0) {
            detail.instance_groups.forEach((group: string) => tags.push(`Group: ${group}`));
          }

          // Add availability info (Available/Running/Total)
          if (detail.available_count !== undefined && detail.running_count !== undefined && detail.total_count !== undefined) {
            // Show: Available X / Running Y / Total Z
            tags.push(`Available: ${detail.available_count}/${detail.running_count} running`);
            if (detail.running_count < detail.total_count) {
              tags.push(`${detail.total_count - detail.running_count} pending`);
            }
          } else if (detail.available_count !== undefined && detail.total_count !== undefined) {
            tags.push(`Available: ${detail.available_count}/${detail.total_count}`);
          }

          // Build description for unavailable instances
          let description: string | undefined;
          if (!isAvailable) {
            if (detail.running_count !== undefined && detail.running_count === 0) {
              description = 'No running instances (all pending)';
            } else {
              description = 'No available instances';
            }
          }

          return {
            label: detail.instance_type,
            value: detail.instance_type,
            tags: tags.length > 0 ? tags : undefined,
            disabled: !isAvailable,
            description: description
          };
        });
      }
      // Fallback to availableInstanceTypes (backward compatibility)
      if (data.availableInstanceTypes?.length > 0) {
        return data.availableInstanceTypes.map((instType: string) => ({
          label: instType,
          value: instType
        }));
      }
      return [];
    }
    // For SageMaker, use predefined INSTANCE_TYPES
    return INSTANCE_TYPES;
  }, [data.deployment_target, data.instanceTypeDetails, data.availableInstanceTypes]);

  // Reset selection when switching deployment target or when HyperPod instance types change
  React.useEffect(() => {
    if (data.deployment_target === 'hyperpod') {
      // When switching to HyperPod, clear selection until cluster is selected and instance types loaded
      if (!data.availableInstanceTypes?.length) {
        setSelectOption(null);
        setData((pre: any) => ({ ...pre, instance_type: '' }));
      } else {
        // Instance types loaded, auto-select first if current selection is invalid
        const currentValue = selectOption?.value;
        if (!data.availableInstanceTypes.includes(currentValue)) {
          const firstAvailable = availableOptions[0];
          if (firstAvailable) {
            setSelectOption(firstAvailable);
            setData((pre: any) => ({ ...pre, instance_type: firstAvailable.value }));
          }
        }
      }
    } else {
      // When switching to SageMaker, clear selection if current is not in SageMaker list
      if (selectOption && !INSTANCE_TYPES.some(opt => opt.value === selectOption.value)) {
        setSelectOption(null);
        setData((pre: any) => ({ ...pre, instance_type: '' }));
      }
    }
  }, [data.deployment_target, data.availableInstanceTypes, availableOptions]);

  return (
    <Select
      selectedOption={selectOption}
      disabled={readOnly}
      onChange={({ detail }) => {
        setSelectOption(detail.selectedOption);
        setData((pre: any) => ({ ...pre, instance_type: detail.selectedOption.value }))
      }}
      options={availableOptions}
      selectedAriaLabel="Selected"
      placeholder={data.deployment_target === 'hyperpod' && availableOptions.length === 0
        ? t("select_cluster_first")
        : t("select_instance_type")
      }
    />
  )
}

const SetEngineType = ({ data, setData, readOnly }: SelectInstanceTypeProps) => {
  const [value, setValue] = useState<string | null>(ENGINE[0].value);
  return (
    <RadioGroup
      items={ENGINE}
      readOnly={readOnly}
      value={value}
      onChange={({ detail }) => {
        setValue(detail.value);
        setData((pre: any) => ({ ...pre, engine: detail.value }))

      }}
    />
  )
}

const SetInstanceQty = ({ data, setData, readOnly }: SelectQuantTypeProps) => {
  const [value, setValue] = useState<string>('1');
  return (
        <Input
          readOnly={readOnly}
          value={value}
          onChange={({ detail }) => {
            setValue(detail.value);
            setData((pre: any) => ({ ...pre, extra_params:{...pre.extra_params,instance_count: detail.value }  }))
          }}
        />
  )
};

const InputEndpointName = ({ data, setData, readOnly }: SelectQuantTypeProps) => {
  const [value, setValue] = useState<string>('');
  return (
    <SpaceBetween size='xs'>
      <FormField
        description={t("custom_endpoint_name_desc")}
        stretch={true}
      >
        <Input
          readOnly={readOnly}
          value={value}
          placeholder={t("endpoint_name_placeholder")}
          onChange={({ detail }) => {
            setValue(detail.value);
            setData((pre: any) => ({ ...pre, extra_params:{...pre.extra_params,endpoint_name: detail.value }  }))
          }}
        />
      </FormField>
    </SpaceBetween>
  )
}


const InputCustRepo = ({ data, setData, readOnly }: SelectQuantTypeProps) => {
  const [value, setValue] = useState<string>('');
  const [typeValue, setTypeValue] = useState<string>('hf');
  return (
    <SpaceBetween size='xs'>
      <FormField
        description={t("custom_model_repo_desc_global")}
        stretch={true}
      >
        <Input
          readOnly={readOnly}
          value={value}
          placeholder='Model Repo'
          onChange={({ detail }) => {
            setValue(detail.value);
            setData((pre: any) => ({ ...pre, cust_repo_addr: detail.value }))
          }}
        />
      </FormField>
    </SpaceBetween>
  )
}

const InputS3Path = ({ data, setData, readOnly }: SelectQuantTypeProps) => {
  const [value, setValue] = useState<string>('');
  return (
    <SpaceBetween size='xs'>
      <FormField
        description={t("custom_model_s3path_desc")}
        stretch={true}
      >
        <S3Selector 
                objectsIsItemDisabled={(item:any) => !item.IsFolder}
                setOutputPath={(value:any)=>
                   setData((pre: any) => ({ ...pre,  extra_params:{...pre.extra_params,s3_model_path: value } }))
                  } 
              outputPath={value}/>
      </FormField>
    </SpaceBetween>
  )
};

const SetExtraSglang = ({ data, setData, readOnly }: SelectQuantTypeProps) => {
  const [contextLen, setContextLen] = useState<string>('');
  const [memFrac, setMemFrac] = useState<string>('');
  const [template, setTemplate] = useState<string>('');
  const [toolCallParser, setToolCallParser] = useState<string>('');
  const [tpSize, setTpSize] = useState<string>('');
  return (
    <SpaceBetween size='xs'>
        <FormField
        label={t("mem_fraction_static")}
        description={t("mem_fraction_static_desc")}
        stretch={false}
      >
        <Input
          readOnly={readOnly}
          value={memFrac}
          placeholder={"0.9"}
          onChange={({ detail }) => {
            setMemFrac(detail.value);
            setData((pre: any) => ({ ...pre, extra_params:{...pre.extra_params,mem_fraction_static: detail.value }  }))
          }}
        />
      </FormField>
      <FormField
        label={t("max_model_len")}
        description={t("max_model_len_desc_sglang")}
        stretch={false}
      >
        <Input
          readOnly={readOnly}
          value={contextLen}
          type="number"
          inputMode="numeric"
          onChange={({ detail }) => {
            setContextLen(detail.value);
            // Convert k to actual value (multiply by 1024)
            const actualValue = detail.value ? String(parseInt(detail.value) * 1024) : '';
            setData((pre: any) => ({ ...pre, extra_params:{...pre.extra_params,max_model_len: actualValue }  }))
          }}
        />
        <Box variant="small" color="text-body-secondary">k (1k = 1024 tokens)</Box>
      </FormField>
      <FormField
        label={t("tensor_parallel_size")}
        description={t("tensor_parallel_size_desc")}
        stretch={false}
      >
        <Input
          readOnly={readOnly}
          value={tpSize}
          onChange={({ detail }) => {
            setTpSize(detail.value);
            setData((pre: any) => ({ ...pre, extra_params:{...pre.extra_params,tensor_parallel_size: detail.value }  }))
          }}
        />
      </FormField>
      <FormField
        label={t("chat_template")}
        description={<Box><Box>{t("chat_template_desc")}</Box>
          <Link external href={"https://docs.sglang.ai/backend/openai_api_vision.html#Chat-Template"} >{t("chat_template_ref")}</Link></Box>}
        stretch={false}
      >
        <Input
          readOnly={readOnly}
          value={template}
          placeholder={"qwen2-vl"}
          onChange={({ detail }) => {
            setTemplate(detail.value);
            setData((pre: any) => ({ ...pre, extra_params:{...pre.extra_params,chat_template: detail.value }  }))
          }}
        />
      </FormField>
        <FormField
        label={t("tool_call_parser")}
        description={<Box><Box>{t("tool_call_parser_desc")}</Box>
          <Link external href={"https://docs.sglang.io/advanced_features/tool_parser.html"} >{t("tool_call_parser_ref")}</Link></Box>}
        stretch={false}
      >
        <Input
          readOnly={readOnly}
          value={toolCallParser}
          placeholder={"qwen25"}
          onChange={({ detail }) => {
            setToolCallParser(detail.value);
            setData((pre: any) => ({ ...pre, extra_params:{...pre.extra_params,tool_call_parser: detail.value }  }))
          }}
        />
      </FormField>
    </SpaceBetween>
  )
}


const SetDeploymentTarget = ({ data, setData, readOnly }: SelectQuantTypeProps) => {
  return (
    <RadioGroup
      items={DEPLOYMENT_TARGETS}
      readOnly={readOnly}
      value={data.deployment_target || 'sagemaker'}
      onChange={({ detail }) => {
        setData((pre: any) => ({ ...pre, deployment_target: detail.value }))
      }}
    />
  )
}

interface ClusterSelectorProps {
  data: any;
  setData: (value: any) => void;
  readOnly: boolean;
}

const SelectHyperPodCluster = ({ data, setData, readOnly }: ClusterSelectorProps) => {
  const [loadStatus, setLoadStatus] = useState<any>("loading");
  const [clusters, setClusters] = useState<any[]>([]);
  const [selectOption, setSelectOption] = useState<SelectProps.Option | null>(null);
  const [loadingInstanceTypes, setLoadingInstanceTypes] = useState(false);

  const handleLoadClusters = async () => {
    setLoadStatus("loading");
    try {
      const response = await remotePost({ page_size: 100, page_index: 1 }, 'list_clusters');
      const clusterList = response.clusters || [];
      // Filter only ACTIVE clusters
      const activeClusters = clusterList.filter((c: any) => c.cluster_status === 'ACTIVE');
      setClusters(activeClusters);
      setLoadStatus("finished");
    } catch (error) {
      console.log(error);
      setLoadStatus("error");
    }
  };

  const handleLoadInstanceTypes = async (clusterId: string) => {
    setLoadingInstanceTypes(true);
    try {
      const response = await remoteGet(`cluster_instance_types/${clusterId}`);
      const body = response?.response?.body || {};
      const instanceTypes = body.instance_types || [];
      const instanceTypeDetails = body.instance_type_details || [];
      setData((pre: any) => ({
        ...pre,
        availableInstanceTypes: instanceTypes,
        instanceTypeDetails: instanceTypeDetails,
        // Auto-select the first available instance type if current selection is invalid
        instance_type: instanceTypes.length > 0 && !instanceTypes.includes(pre.instance_type)
          ? instanceTypes[0]
          : pre.instance_type
      }));
    } catch (error) {
      console.log('Failed to load instance types:', error);
      setData((pre: any) => ({ ...pre, availableInstanceTypes: [], instanceTypeDetails: [] }));
    }
    setLoadingInstanceTypes(false);
  };

  useEffect(() => {
    if (data.deployment_target === 'hyperpod') {
      handleLoadClusters();
    }
  }, [data.deployment_target]);

  return (
    <Select
      statusType={loadStatus}
      onLoadItems={handleLoadClusters}
      disabled={readOnly || loadingInstanceTypes}
      selectedOption={selectOption}
      placeholder={loadingInstanceTypes ? t("loading_instance_types") : t("select_hyperpod_cluster")}
      onChange={({ detail }) => {
        setSelectOption(detail.selectedOption);
        const clusterId = detail.selectedOption?.value;
        setData((pre: any) => ({ ...pre, hyperpod_cluster_id: clusterId }));
        // Fetch available instance types for this cluster
        if (clusterId) {
          handleLoadInstanceTypes(clusterId);
        }
      }}
      options={clusters.map((cluster) => ({
        label: cluster.cluster_name,
        value: cluster.cluster_id,
        description: `EKS: ${cluster.eks_cluster_name}`
      }))}
      selectedAriaLabel="Selected"
    />
  )
}

const SetHyperPodReplicas = ({ data, setData, readOnly }: SelectQuantTypeProps) => {
  const [value, setValue] = useState<string>('1');
  return (
    <Input
      readOnly={readOnly}
      value={value}
      type="number"
      onChange={({ detail }) => {
        setValue(detail.value);
        setData((pre: any) => ({
          ...pre,
          hyperpod_config: { ...pre.hyperpod_config, replicas: parseInt(detail.value) || 1 }
        }))
      }}
    />
  )
}

const SetHyperPodNamespace = ({ data, setData, readOnly }: SelectQuantTypeProps) => {
  const [value, setValue] = useState<string>('default');
  return (
    <Input
      readOnly={readOnly}
      value={value}
      placeholder="default"
      onChange={({ detail }) => {
        setValue(detail.value);
        setData((pre: any) => ({
          ...pre,
          hyperpod_config: { ...pre.hyperpod_config, namespace: detail.value || 'default' }
        }))
      }}
    />
  )
}

// HyperPod Auto-scaling Configuration
const SetHyperPodAutoscaling = ({ data, setData, readOnly }: SelectQuantTypeProps) => {
  const [enabled, setEnabled] = useState<boolean>(false);
  const [minReplicas, setMinReplicas] = useState<string>('1');
  const [maxReplicas, setMaxReplicas] = useState<string>('10');

  return (
    <SpaceBetween size="s">
      <Toggle
        readOnly={readOnly}
        checked={enabled}
        onChange={({ detail }) => {
          setEnabled(detail.checked);
          setData((pre: any) => ({
            ...pre,
            hyperpod_config: { ...pre.hyperpod_config, enable_autoscaling: detail.checked }
          }))
        }}
      >
        {t("enable_autoscaling")}
      </Toggle>
      {enabled && (
        <SpaceBetween size="s" direction="horizontal">
          <FormField label={t("min_replicas")}>
            <Input
              readOnly={readOnly}
              value={minReplicas}
              type="number"
              onChange={({ detail }) => {
                setMinReplicas(detail.value);
                setData((pre: any) => ({
                  ...pre,
                  hyperpod_config: { ...pre.hyperpod_config, min_replicas: parseInt(detail.value) || 1 }
                }))
              }}
            />
          </FormField>
          <FormField label={t("max_replicas")}>
            <Input
              readOnly={readOnly}
              value={maxReplicas}
              type="number"
              onChange={({ detail }) => {
                setMaxReplicas(detail.value);
                setData((pre: any) => ({
                  ...pre,
                  hyperpod_config: { ...pre.hyperpod_config, max_replicas: parseInt(detail.value) || 10 }
                }))
              }}
            />
          </FormField>
        </SpaceBetween>
      )}
    </SpaceBetween>
  )
}

// HyperPod KV Cache Configuration
const SetHyperPodKVCache = ({ data, setData, readOnly }: SelectQuantTypeProps) => {
  const [enabled, setEnabled] = useState<boolean>(false);
  const [enableL2, setEnableL2] = useState<boolean>(false);  // Disabled by default due to operator bug
  const [backend, setBackend] = useState<SelectProps.Option | null>(KV_CACHE_BACKENDS[0]);

  return (
    <SpaceBetween size="s">
      <Toggle
        readOnly={readOnly}
        checked={enabled}
        onChange={({ detail }) => {
          setEnabled(detail.checked);
          setData((pre: any) => ({
            ...pre,
            hyperpod_config: { ...pre.hyperpod_config, enable_kv_cache: detail.checked }
          }))
        }}
      >
        {t("enable_kv_cache")}
      </Toggle>
      {enabled && (
        <SpaceBetween size="s">
          <Toggle
            readOnly={readOnly}
            disabled={true}  // Temporarily disabled due to HyperPod operator bug (lmcache-config volume mount error)
            checked={enableL2}
            onChange={({ detail }) => {
              setEnableL2(detail.checked);
              setData((pre: any) => ({
                ...pre,
                hyperpod_config: { ...pre.hyperpod_config, enable_l2_cache: detail.checked }
              }))
            }}
          >
            {t("enable_l2_cache")} (Temporarily disabled)
          </Toggle>
          {enableL2 && (
            <FormField label={t("kv_cache_backend")}>
              <Select
                disabled={readOnly}
                selectedOption={backend}
                onChange={({ detail }) => {
                  setBackend(detail.selectedOption);
                  setData((pre: any) => ({
                    ...pre,
                    hyperpod_config: { ...pre.hyperpod_config, kv_cache_backend: detail.selectedOption?.value || 'tieredstorage' }
                  }))
                }}
                options={KV_CACHE_BACKENDS}
                selectedAriaLabel="Selected"
              />
            </FormField>
          )}
        </SpaceBetween>
      )}
    </SpaceBetween>
  )
}

// HyperPod Intelligent Routing Configuration
const SetHyperPodIntelligentRouting = ({ data, setData, readOnly }: SelectQuantTypeProps) => {
  const [enabled, setEnabled] = useState<boolean>(false);
  const [strategy, setStrategy] = useState<SelectProps.Option | null>(ROUTING_STRATEGIES[0]);

  return (
    <SpaceBetween size="s">
      <Toggle
        readOnly={readOnly}
        checked={enabled}
        onChange={({ detail }) => {
          setEnabled(detail.checked);
          setData((pre: any) => ({
            ...pre,
            hyperpod_config: { ...pre.hyperpod_config, enable_intelligent_routing: detail.checked }
          }))
        }}
      >
        {t("enable_intelligent_routing")}
      </Toggle>
      {enabled && (
        <FormField label={t("routing_strategy")}>
          <Select
            disabled={readOnly}
            selectedOption={strategy}
            onChange={({ detail }) => {
              setStrategy(detail.selectedOption);
              setData((pre: any) => ({
                ...pre,
                hyperpod_config: { ...pre.hyperpod_config, routing_strategy: detail.selectedOption?.value || 'prefixaware' }
              }))
            }}
            options={ROUTING_STRATEGIES}
            selectedAriaLabel="Selected"
          />
        </FormField>
      )}
    </SpaceBetween>
  )
}

const SetHyperPodPublicALB = ({ data, setData, readOnly }: SelectQuantTypeProps) => {
  const [enabled, setEnabled] = useState(data.hyperpod_config?.use_public_alb || false);
  const [enableApiKey, setEnableApiKey] = useState(data.hyperpod_config?.enable_api_key || false);
  const [apiKeySource, setApiKeySource] = useState<SelectProps.Option | null>(API_KEY_SOURCES[0]);
  const [customApiKey, setCustomApiKey] = useState('');
  const [secretName, setSecretName] = useState('');

  // Check if intelligent routing is enabled
  const intelligentRoutingEnabled = data.hyperpod_config?.enable_intelligent_routing || false;

  // Auto-disable public ALB when intelligent routing is disabled
  React.useEffect(() => {
    if (enabled && !intelligentRoutingEnabled) {
      setEnabled(false);
      setData((pre: any) => ({
        ...pre,
        hyperpod_config: { ...pre.hyperpod_config, use_public_alb: false }
      }));
    }
  }, [intelligentRoutingEnabled]);

  // Auto-enable API key when public ALB is enabled
  React.useEffect(() => {
    if (enabled && !enableApiKey) {
      setEnableApiKey(true);
      setData((pre: any) => ({
        ...pre,
        hyperpod_config: { ...pre.hyperpod_config, enable_api_key: true }
      }));
    }
  }, [enabled]);

  return (
    <SpaceBetween size="s">
      {/* Show info alert when intelligent routing is disabled */}
      {!intelligentRoutingEnabled && (
        <Alert type="info">
          {t("public_alb_requires_routing")}
        </Alert>
      )}
      <Toggle
        readOnly={readOnly}
        disabled={!intelligentRoutingEnabled}
        checked={enabled}
        onChange={({ detail }) => {
          // Prevent enabling if intelligent routing is disabled
          if (detail.checked && !intelligentRoutingEnabled) {
            return;
          }
          setEnabled(detail.checked);
          // Auto-enable API key when public ALB is enabled
          const newEnableApiKey = detail.checked ? true : enableApiKey;
          setEnableApiKey(newEnableApiKey);
          setData((pre: any) => ({
            ...pre,
            hyperpod_config: {
              ...pre.hyperpod_config,
              use_public_alb: detail.checked,
              enable_api_key: newEnableApiKey
            }
          }))
        }}
      >
        {t("use_public_alb")}
      </Toggle>
      {enabled && (
        <SpaceBetween size="s">
          <Alert type="warning">
            {t("public_alb_warning")}
          </Alert>

          {/* API Key Configuration - strongly recommended for public ALB */}
          <FormField
            label={t("api_key_auth")}
            description={t("api_key_auth_desc")}
          >
            <Toggle
              readOnly={readOnly}
              checked={enableApiKey}
              onChange={({ detail }) => {
                setEnableApiKey(detail.checked);
                setData((pre: any) => ({
                  ...pre,
                  hyperpod_config: { ...pre.hyperpod_config, enable_api_key: detail.checked }
                }))
              }}
            >
              {t("enable_api_key")}
            </Toggle>
          </FormField>

          {enableApiKey && (
            <SpaceBetween size="s">
              <FormField label={t("api_key_source")}>
                <Select
                  disabled={readOnly}
                  selectedOption={apiKeySource}
                  onChange={({ detail }) => {
                    setApiKeySource(detail.selectedOption);
                    setData((pre: any) => ({
                      ...pre,
                      hyperpod_config: { ...pre.hyperpod_config, api_key_source: detail.selectedOption?.value || 'auto' }
                    }))
                  }}
                  options={API_KEY_SOURCES}
                  selectedAriaLabel="Selected"
                />
              </FormField>

              {apiKeySource?.value === 'custom' && (
                <FormField
                  label={t("custom_api_key")}
                  description={t("custom_api_key_desc")}
                >
                  <Input
                    readOnly={readOnly}
                    value={customApiKey}
                    type="password"
                    placeholder="sk-xxxxxxxxxxxxxxxx"
                    onChange={({ detail }) => {
                      setCustomApiKey(detail.value);
                      setData((pre: any) => ({
                        ...pre,
                        hyperpod_config: { ...pre.hyperpod_config, custom_api_key: detail.value }
                      }))
                    }}
                  />
                </FormField>
              )}

              {apiKeySource?.value === 'secrets_manager' && (
                <FormField
                  label={t("secrets_manager_secret")}
                  description={t("secrets_manager_secret_desc")}
                >
                  <Input
                    readOnly={readOnly}
                    value={secretName}
                    placeholder="vllm/api-key"
                    onChange={({ detail }) => {
                      setSecretName(detail.value);
                      setData((pre: any) => ({
                        ...pre,
                        hyperpod_config: { ...pre.hyperpod_config, secrets_manager_secret_name: detail.value }
                      }))
                    }}
                  />
                </FormField>
              )}
            </SpaceBetween>
          )}
        </SpaceBetween>
      )}
    </SpaceBetween>
  )
}

const SetExtraParamsInput = ({ data, setData, readOnly }: SelectQuantTypeProps) => {
  // const DEFAULT_MAX_MODEL_LEN = '12288';
  const [value1, setValue1] = useState<string>('');
  const [value2, setValue2] = useState<string>('');
  const [valueMaxNumSeqs, setMaxNumSeqs] = useState<string>('');
  const DEFAULT_ENABLE_PROMPT_CACHE = true;
  const [value3, setValue3] = useState<boolean>(DEFAULT_ENABLE_PROMPT_CACHE);
  const [value4, setValue4] = useState<boolean>(false);
  const [toolCallParser, setToolCallParser] = useState<string>('');


  React.useEffect(() => {
    setData((pre: any) => ({
      ...pre,
      extra_params: { ...pre.extra_params, enable_prefix_caching: DEFAULT_ENABLE_PROMPT_CACHE }
    }));
  }, []);

  return (
    <SpaceBetween size='xs'>
      <FormField
        label={t("max_model_len")}
        description={t("max_model_len_desc_vllm")}
        stretch={false}
      >
        <Input
          readOnly={readOnly}
          value={value1}
          type="number"
          placeholder='12'
          inputMode="numeric"
          onChange={({ detail }) => {
            setValue1(detail.value);
            // Convert k to actual value (multiply by 1024)
            const actualValue = detail.value ? String(parseInt(detail.value) * 1024) : '';
            setData((pre: any) => ({ ...pre, extra_params:{...pre.extra_params,max_model_len: actualValue }  }))
          }}
        />
        <Box variant="small" color="text-body-secondary">k (1k = 1024 tokens)</Box>
      </FormField>
      <FormField
        label={t("tensor_parallel_size")}
        description={t("tensor_parallel_size_desc")}
        stretch={false}
      >
        <Input
          readOnly={readOnly}
          value={value2}
          onChange={({ detail }) => {
            setValue2(detail.value);
            setData((pre: any) => ({ ...pre,  extra_params:{...pre.extra_params,tensor_parallel_size: detail.value } }))
          }}
        />
      </FormField>
        <FormField
        label={t("tool_call_parser")}
        description={<Box><Box>{t("tool_call_parser_desc")}</Box>
          <Link external href={"https://docs.vllm.ai/en/latest/features/tool_calling.html#xlam-models-xlam"} >{t("tool_call_parser_ref")}</Link></Box>}
        stretch={false}
      >
        <Input
          readOnly={readOnly}
          value={toolCallParser}
          placeholder={"hermes"}
          onChange={({ detail }) => {
            setToolCallParser(detail.value);
            setData((pre: any) => ({ ...pre, extra_params:{...pre.extra_params,tool_call_parser: detail.value }  }))
          }}
        />
      </FormField>
      <FormField
        label={t("enable_prefix_caching")}
        description={t("enable_prefix_caching_desc")}
        stretch={false}
      >
        <Toggle
          readOnly={readOnly}
          checked={value3}
          onChange={({ detail }) => {
            setValue3(detail.checked);
            setData((pre: any) => ({ ...pre, extra_params:{...pre.extra_params,enable_prefix_caching: detail.checked }  }))
          }}
        >
          {t("enable")}
        </Toggle>
      </FormField>
      <FormField
        label={t("enforce_eager")}
        description={t("enforce_eager_desc")}
        stretch={false}
      >
        <Toggle
          readOnly={readOnly}
          checked={value4}
          onChange={({ detail }) => {
            setValue4(detail.checked);
            setData((pre: any) => ({ ...pre, extra_params:{...pre.extra_params,enforce_eager: detail.checked }  }))
          }}
        >
          {t("enable")}
        </Toggle>
      </FormField>
      <FormField
        label={t("max_num_seqs")}
        description={t("max_num_seqs_desc")}
        stretch={false}
      >
        <Input
          readOnly={readOnly}
          value={valueMaxNumSeqs}
          placeholder='256'
          onChange={({ detail }) => {
            setMaxNumSeqs(detail.value);
            setData((pre: any) => ({ ...pre, extra_params:{...pre.extra_params,max_num_seqs: detail.value }  }))
          }}
        />
      </FormField>
    </SpaceBetween>
  )
}

export const DeployModelModal = ({
  extraActions = null,
  selectedItems,
  visible,
  setVisible,
  setDisplayNotify,
  setNotificationData,
  onRefresh,
  ...props
}: PageHeaderProps) => {
  const [errors, _setErrors] = useState(defaultErrors);
  const [data, setData] = useState(defaultData);
  const [loading, setLoading] = useState(false);
  const { setNotificationItems } = useSimpleNotifications();
  const navigate = useNavigate();

  useEffect(() => {
    setData((pre: any) => ({ ...pre, model_name: selectedItems[0]?.job_payload?.model_name }));
  }, [])
  const modelNameReadOnly = selectedItems[0]?.job_payload?.model_name ? true : false;

  // console.log(selectedItems)
  const onDeloyConfirm = () => {
    setLoading(true);
    const msgid = `msg-${Math.random().toString(8)}`;
    const jobId = selectedItems[0]?.job_id ?? "N/A(Not finetuned)";
    const fromData = { ...data, job_id: jobId }
    remotePost(fromData, 'deploy_endpoint').
      then(res => {
        if (res.response.result) {
          setVisible(false);
          setLoading(false);
          setNotificationItems((item: any) => [
            ...item,
            {
              type: "success",
              content: `${t("create_endpoint_success")}:${res.response.endpoint_name}`,
              dismissible: true,
              dismissLabel: "Dismiss message",
              onDismiss: () =>
                setNotificationItems((items: any) =>
                  items.filter((item: any) => item.id !== msgid)
                ),
              id: msgid,
            },
          ]);
          onRefresh?.();
          navigate('/endpoints');
        } else {
          setVisible(false);
          setLoading(false);
          setNotificationItems((item: any) => [
            ...item,
            {
              type: "error",
              content: `${t("create_endpoint_failed")}:${res.response.endpoint_name}`,
              dismissible: true,
              dismissLabel: "Dismiss message",
              onDismiss: () =>
                setNotificationItems((items: any) =>
                  items.filter((item: any) => item.id !== msgid)
                ),
              id: msgid,
            },
          ]);
          onRefresh?.();
        }

      })
      .catch(err => {
        setVisible(false);
        setNotificationItems((item: any) => [
          ...item,
          {
            type: "error",
            content: `${t("create_endpoint_failed")}:${err}`,
            dismissible: true,
            dismissLabel: "Dismiss message",
            onDismiss: () =>
              setNotificationItems((items: any) =>
                items.filter((item: any) => item.id !== msgid)
              ),
            id: msgid,
          },
        ]);
        onRefresh?.();
        setLoading(false);
      })
  }
  return (
    <Modal
      onDismiss={() => setVisible(false)}
      visible={visible}
      footer={
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" onClick={() => setVisible(false)}>{t("cancel")}</Button>
            <Button variant="primary" onClick={onDeloyConfirm}
              loading={loading}
              disabled={loading}
            >{t("confirm")}</Button>
          </SpaceBetween>
        </Box>
      }
      header={t("deploy_model_endpoint")}
    ><SpaceBetween size="l">
        <FormField
          label={t("deployment_target")}
          stretch={false}
          description={t("deployment_target_desc")}
        >
          <SetDeploymentTarget data={data} setData={setData} readOnly={false} />
        </FormField>

        {/* SageMaker: Instance type and count right after deployment target */}
        {data.deployment_target === 'sagemaker' && (
          <>
            <FormField
              label={t("instance_type")}
              stretch={false}
              errorText={errors.instance_type}
              i18nStrings={{ errorIconAriaLabel: 'Error' }}
            >
              <SelectInstanceType data={data} setData={setData} readOnly={false} />
            </FormField>

            <FormField
              label={t("instance_qty")}
              description={t("instance_qty_desc")}
              stretch={false}
              errorText={errors.instance_count}
              i18nStrings={{ errorIconAriaLabel: 'Error' }}
            >
              <SetInstanceQty data={data} setData={setData} readOnly={false} />
            </FormField>
          </>
        )}

        {data.deployment_target === 'hyperpod' && (
          <>
            <FormField
              label={t("hyperpod_cluster")}
              stretch={false}
              description={t("hyperpod_cluster_desc")}
            >
              <SelectHyperPodCluster data={data} setData={setData} readOnly={false} />
            </FormField>

            <FormField
              label={t("instance_type")}
              stretch={false}
              errorText={errors.instance_type}
              i18nStrings={{ errorIconAriaLabel: 'Error' }}
            >
              <SelectInstanceType data={data} setData={setData} readOnly={false} />
            </FormField>

            <FormField
              label={t("replicas")}
              stretch={false}
              description={t("replicas_desc")}
            >
              <SetHyperPodReplicas data={data} setData={setData} readOnly={false} />
            </FormField>

            <FormField
              label={t("autoscaling")}
              stretch={false}
              description={t("autoscaling_desc")}
            >
              <SetHyperPodAutoscaling data={data} setData={setData} readOnly={false} />
            </FormField>

            <FormField
              label={t("kv_cache")}
              stretch={false}
              description={t("kv_cache_desc")}
            >
              <SetHyperPodKVCache data={data} setData={setData} readOnly={false} />
            </FormField>

            <FormField
              label={t("intelligent_routing")}
              stretch={false}
              description={t("intelligent_routing_desc")}
            >
              <SetHyperPodIntelligentRouting data={data} setData={setData} readOnly={false} />
            </FormField>

            <FormField
              label={t("public_alb")}
              stretch={false}
              description={t("public_alb_desc")}
            >
              <SetHyperPodPublicALB data={data} setData={setData} readOnly={false} />
            </FormField>
          </>
        )}

        <FormField
          label={t("model_name")}
          stretch={false}
          description={t("select_supported_model")}
          i18nStrings={{ errorIconAriaLabel: 'Error' }}
        >
          <SelectModelName data={data} setData={setData} readOnly={modelNameReadOnly} />
        </FormField>
        <FormField
          label={t("custom_endpoint_name")}
          stretch={false}
        >
          <InputEndpointName data={data} setData={setData} readOnly={false} />
        </FormField>
        <FormField
          label={t("custom_model_repo")}
          stretch={false}
        >
          <InputCustRepo data={data} setData={setData} readOnly={modelNameReadOnly} />
        </FormField>
        {/* S3 path is only for SageMaker deployments */}
        {data.deployment_target === 'sagemaker' && (
          <FormField
            label={t("custom_model_s3path")}
            stretch={false}
          >
            <InputS3Path data={data} setData={setData} readOnly={modelNameReadOnly} />
          </FormField>
        )}

        <FormField
          label={t("engine_type")}
          stretch={false}
          errorText={errors.engine}
          description={<Link href='https://docs.djl.ai/docs/serving/serving/docs/lmi/user_guides/vllm_user_guide.html' external>{t("engine_support_info")}</Link>}
          i18nStrings={{ errorIconAriaLabel: 'Error' }}
        >
          <SetEngineType data={data} setData={setData} readOnly={false} />
        </FormField>

        {data.engine === 'vllm' &&
          <SetExtraParamsInput data={data} setData={setData} readOnly={false} />}

        {data.engine === 'sglang' && 
          <SetExtraSglang data={data} setData={setData} readOnly={false} />}
      </SpaceBetween>
    </Modal>
  );
}